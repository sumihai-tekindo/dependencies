# -*- coding: utf-8 -*-
import logging
import werkzeug
import json

from openerp import SUPERUSER_ID
from openerp import http
from openerp import tools
from openerp.http import request
from openerp.tools.translate import _
from openerp.addons.website.models.website import slug
from openerp.addons.web.controllers.main import login_redirect


class analytic_api(http.Controller):

	@http.route(['/cabang/',], type='http', auth="public")
	def api_analytic(self,**post):
		cr, uid, context, pool = request.cr, request.uid, request.context, request.registry
		analytic_ids = pool.get('account.analytic.account').search(cr,SUPERUSER_ID,[('tag','in',['cabang','transit','gerai','perwakilan','agen','toko'])]) 
		analytic = pool.get('account.analytic.account').browse(cr,SUPERUSER_ID,analytic_ids)
		result = []
		for aa in analytic:
			result.append({
				'id': aa.id,
				'nama_cabang': aa.name or '',
				'kode_cabang': aa.code or '',
				'nama_kota'	 : aa.parent_id and aa.parent_id.name or '',
				'kode_kota'	 : aa.parent_id and aa.parent_id.code or '',
				'nama_provinsi': aa.parent_id and aa.parent_id.parent_id and aa.parent_id.parent_id.name or '',
				'id_rds':aa.rds_id or 'NULL',
				'alias_name':aa.alias_name or 'NULL',
				'kode_provinsi': aa.parent_id and aa.parent_id.parent_id and aa.parent_id.parent_id.code or '',
				})
		final_result = {'kode_cabang':result}
		return str(json.dumps(final_result))