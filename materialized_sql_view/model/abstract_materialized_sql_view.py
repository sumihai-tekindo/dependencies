# -*- coding: utf-8 -*-

import psycopg2
import logging
from openerp.osv import osv
from openerp import SUPERUSER_ID
from abc import ABCMeta, abstractmethod

logger = logging.getLogger(__name__)
ABSTRACT_MODEL_NAME = 'abstract.materialized.sql.view'


class AbstractMaterializedSqlView(osv.AbstractModel):
    """This class is an abstract model to help developer to create/refresh/update
       materialized view.
    """
    _name = ABSTRACT_MODEL_NAME
    _description = u"This is an helper class to manage materialized SQL view"
    _auto = False

    _sql_mat_view_name = ''
    """The name of the materialized sql view.
       Must be defined in inherit class (using inherit = [])
    """
    _sql_view_name = ''
    """The name of the sql view used to generate the materialized view
       Must be defined in inherit class (using inherit = [])
    """
    _sql_view_definition = ''
    """The sql query to generate the view (without any create views)
    """
    
    def init(self, cr):
        """Init method is called when installing or updating the module.
           As we can't know if the model of the sql changed, we have to drop materialized view
           and recreate it.
        """
        if hasattr(super(AbstractMaterializedSqlView, self), 'init'):
            super(self, AbstractMaterializedSqlView).init(cr)

        # prevent against Abstract class initialization
        if self._name == ABSTRACT_MODEL_NAME:
            return

        logger.info(u"Init materialized view, using Postgresql %r",
                    cr._cnx.server_version)
        self.create_or_upgrade_pg_matview_if_needs(cr, SUPERUSER_ID)

    def safe_properties(self):
        if not self._sql_view_definition:
            raise osv.except_osv(u"Properties must be defined in subclass",
                                 u"_sql_view_definition properties should be redifined in sub class"
                                 )
        if not self._sql_mat_view_name:
            self._sql_mat_view_name = self._table
        if not self._sql_view_name:
            self._sql_view_name = self._table + '_view'

    def create_materialized_view(self, cr, uid, context=None):
        self.safe_properties()
        if not context:
            context = {}
        result = []
        logger.info("Create Materialized view %r", self._sql_mat_view_name)
        pg_version = context.get('force_pg_version', cr._cnx.server_version)
        self.change_matview_state(cr, uid, 'before_create_view', pg_version, context=context)
        try:
            pg = PGMaterializedViewManager.getInstance(pg_version)
            # make sure there is no existing views create uppon the same version
            # this could be possible if materialized.sql.view entry is deleted
            # TODO: maybe move it in create_or_upgrade_pg_matview_if_needs and
            # automaticly detect if it's a mat view or a table cf utests
            pg.drop_mat_view(cr, self._sql_view_name, self._sql_mat_view_name)
            self.before_create_materialized_view(cr, uid, context=context)
            pg.create_mat_view(cr, self._sql_view_definition, self._sql_view_name,
                               self._sql_mat_view_name)
            self.after_create_materialized_view(cr, uid, context=context)
        except psycopg2.Error as e:
            self.report_sql_error(cr, uid, e, pg_version, context=context)
        else:
            result = self.change_matview_state(cr, uid, 'after_refresh_view', pg_version,
                                               context=context)
        return result

    def refresh_materialized_view(self, cr, uid, context=None):
        self.safe_properties()
        result = self.create_or_upgrade_pg_matview_if_needs(cr, uid, context=context)
        if not result:
            logger.info("Refresh Materialized view %r", self._sql_mat_view_name)
            if not context:
                context = {}
            pg_version = context.get('force_pg_version', cr._cnx.server_version)
            self.change_matview_state(cr, uid, 'before_refresh_view', pg_version,
                                      context)
            try:
                self.before_refresh_materialized_view(cr, uid, context=context)
                pg = PGMaterializedViewManager.getInstance(pg_version)
                pg.refresh_mat_view(cr, self._sql_view_name, self._sql_mat_view_name)
                self.after_refresh_materialized_view(cr, uid, context=context)
            except psycopg2.Error as e:
                self.report_sql_error(cr, uid, e, pg_version, context=context)
            else:
                result = self.change_matview_state(cr, uid, 'after_refresh_view', pg_version,
                                                   context=context)
        return result

    def create_or_upgrade_pg_matview_if_needs(self, cr, uid, context=None):
        """Compare everything that can cause the needs to drop and recreate materialized view
           Return True if something done
        """
        self.safe_properties()
        matview_mdl = self.pool.get('materialized.sql.view')
        if not context:
            context = {}
        ids = matview_mdl.search_materialized_sql_view_ids_from_matview_name(
            cr, uid, self._sql_mat_view_name, context=context)
        if ids:
            # As far matview_mdl is refered by its view name, to get one or more instance
            # is technicly the same.
            id = ids[0]
            rec = matview_mdl.read(cr, uid, id, ['pg_version', 'sql_definition', 'view_name',
                                                 'state'],
                                   context=context)
            pg_version = context.get('force_pg_version', cr._cnx.server_version)
            pg = PGMaterializedViewManager.getInstance(cr._cnx.server_version)
            if(rec['pg_version'] != pg_version or
               rec['sql_definition'] != self._sql_view_definition or
               rec['view_name'] != self._sql_view_name or
               rec['state'] in ['nonexistent', 'aborted'] or
               not pg.is_existed_relation(cr, self._sql_view_name) or
               not pg.is_existed_relation(cr, self._sql_mat_view_name)):
                self.drop_materialized_view_if_exist(cr, uid, rec['pg_version'],
                                                     view_name=rec['view_name'],
                                                     context=context)
            else:
                return []

        return self.create_materialized_view(cr, uid, context=context)

    def change_matview_state(self, cr, uid, method_name, pg_version, context=None):
        matview_mdl = self.pool.get('materialized.sql.view')
        # Make sure object exist or create it
        values = {
            'model_name': self._name,
            'view_name': self._sql_view_name,
            'matview_name': self._sql_mat_view_name,
            'sql_definition': self._sql_view_definition,
            'pg_version': pg_version,
        }
        matview_mdl.create_if_not_exist(cr, uid, values, context=context)
        method = getattr(matview_mdl, method_name)
        context.update({'values': values})
        return method(cr, uid, self._sql_mat_view_name, context=context)

    def drop_materialized_view_if_exist(self, cr, uid, pg_version, view_name=None,
                                        mat_view_name=None, context=None):
        self.safe_properties()
        result = []
        logger.info("Drop Materialized view %r", self._sql_mat_view_name)
        try:
            self.before_drop_materialized_view(cr, uid, context=context)
            pg = PGMaterializedViewManager.getInstance(pg_version)
            if not view_name:
                view_name = self._sql_view_name
            if not mat_view_name:
                mat_view_name = self._sql_mat_view_name
            pg.drop_mat_view(cr, view_name, mat_view_name)
            self.after_drop_materialized_view(cr, uid, context=context)
        except psycopg2.Error as e:
            self.report_sql_error(cr, uid, e, pg_version, context=context)
        else:
            result = self.change_matview_state(cr, uid, 'after_drop_view', pg_version,
                                               context=context)
        return result

    def report_sql_error(self, cr, uid, err, pg_version, context=None):
        if not context:
            context = {}
        context.update({'error_message': err.pgerror})
        cr.rollback()
        self.change_matview_state(cr, uid, 'aborted_matview', pg_version, context=context)

    def before_drop_materialized_view(self, cr, uid, context=None):
        """Method called before drop materialized view and view,
           Nothing done in abstract method, it's  hook to used in subclass
        """

    def after_drop_materialized_view(self, cr, uid, context=None):
        """Method called after drop materialized view and view,
           Nothing done in abstract method, it's  hook to used in subclass
        """

    def before_create_materialized_view(self, cr, uid, context=None):
        """Method called before create materialized view and view,
           Nothing done in abstract method, it's  hook to used in subclass
        """

    def after_create_materialized_view(self, cr, uid, context=None):
        """Method called after create materialized view and view,
           Nothing done in abstract method, it's  hook to used in subclass
        """

    def before_refresh_materialized_view(self, cr, uid, context=None):
        """Method called before refresh materialized view,
           this was made to do things like drop index before in the same transaction.

           Nothing done in abstract method, it's  hook to used in subclass
        """

    def after_refresh_materialized_view(self, cr, uid, context=None):
        """Method called after refresh materialized view,
           this was made to do things like add index after refresh data

           Nothing done in abstract method, it's  hook to used in subclass
        """

    def write(self, cr, uid, ids, context=None):
        raise osv.except_osv(u"Write on materialized view is forbidden",
                             u"Write on materialized view is forbidden,"
                             u"because data would be lost at the next refresh"
                             )

    def create(self, cr, uid, ids, context=None):
        raise osv.except_osv(u"Create data on materialized view is forbidden",
                             u"Create data on materialized view is forbidden,"
                             u"because data would be lost at the next refresh"
                             )

    def unlink(self, cr, uid, ids, context=None):
        raise osv.except_osv(u"Remove data on materialized view is forbidden",
                             u"Remove data on materialized view is forbidden,"
                             u"because data would be lost at the next refresh"
                             )


class PGMaterializedViewManager(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def create_mat_view(self, cr, sql, view_name, mat_view_name):
        """Abstract Method to overwrite in subclass to create sql view
           and materialized sql view from sql query.
        """

    @abstractmethod
    def refresh_mat_view(self, cr, view_name, mat_view_name):
        """Abstract Method  to overwrite in subclass to refresh
           materialized sql view
        """

    @abstractmethod
    def drop_mat_view(self, cr, view_name, mat_view_name):
        """Abstract Method to overwrite in subclass to drop materialized view and clean
           every thing to its authority
        """

    def is_existed_relation(self, cr, relname):
        cr.execute("select count(*) from pg_class where relname like '%(relname)s'" %
                   {'relname': relname})
        return cr.fetchone()[0] > 0

    @classmethod
    def getInstance(cls, version):
        """Method that return the class depending pg server_version
        """
        if version >= 90300:
            return PG090300()
        else:
            return PGNoMaterializedViewSupport()


class PGNoMaterializedViewSupport(PGMaterializedViewManager):

    def create_mat_view(self, cr, sql, view_name, mat_view_name):
        cr.execute("CREATE VIEW %(view_name)s AS (%(sql)s)" %
                   dict(view_name=view_name, sql=sql, ))
        cr.execute("CREATE TABLE %(mat_view_name)s AS SELECT * FROM %(view_name)s" %
                   dict(mat_view_name=mat_view_name,
                        view_name=view_name,
                        ))

    def refresh_mat_view(self, cr, view_name, mat_view_name):
        cr.execute("DELETE FROM %(mat_view_name)s" % dict(mat_view_name=mat_view_name,
                                                          ))
        cr.execute("INSERT INTO %(mat_view_name)s SELECT * FROM %(view_name)s" %
                   dict(mat_view_name=mat_view_name,
                        view_name=view_name,
                        ))

    def drop_mat_view(self, cr, view_name, mat_view_name):
        cr.execute("DROP TABLE IF EXISTS %s CASCADE" % (mat_view_name))
        cr.execute("DROP VIEW IF EXISTS %s CASCADE" % (view_name,))


class PG090300(PGMaterializedViewManager):

    def create_mat_view(self, cr, sql, view_name, mat_view_name):
        cr.execute("CREATE VIEW %(view_name)s AS (%(sql)s)" %
                   dict(view_name=view_name, sql=sql, ))
        cr.execute("CREATE MATERIALIZED VIEW %(mat_view_name)s AS SELECT * FROM %(view_name)s" %
                   dict(mat_view_name=mat_view_name,
                        view_name=view_name,
                        ))

    def refresh_mat_view(self, cr, view_name, mat_view_name):
        cr.execute("REFRESH MATERIALIZED VIEW %(mat_view_name)s" %
                   dict(mat_view_name=mat_view_name,
                        ))

    def drop_mat_view(self, cr, view_name, mat_view_name):
        cr.execute("DROP MATERIALIZED VIEW IF EXISTS %s CASCADE" % (mat_view_name))
        cr.execute("DROP VIEW IF EXISTS %s CASCADE" % (view_name,))
