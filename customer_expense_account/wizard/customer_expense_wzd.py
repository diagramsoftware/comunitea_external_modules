# -*- coding: utf-8 -*-
# © 2016 Comunitea - Javier Colmenero <javier@comunitea.com>
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html


from openerp import models, api, fields, _
from openerp.exceptions import except_orm
import time
# from models.expense_type import COMPUTE_TYPES
COMPUTE_TYPES = [
    ('analytic', 'Based on analytic account'),
    ('ratio', 'Based on parent element'),
    ('total_cost', 'Total Cost'),
    ('total_margin', 'Total Margin'),
    ('distribution', 'Based on analytic distribution'),
]


class CustomerExpenseWzd(models.TransientModel):
    _name = 'customer.expense.wzd'

    start_date = fields.Date('Start Date')
    end_date = fields.Date('End Date')

    @api.model
    def default_get(self, fields):
        res = super(CustomerExpenseWzd, self).default_get(fields)
        year = str(time.strftime("%Y"))
        date_start = year + '-' + '01' + '-' + '01'
        date_end = year + '-' + '12' + '-' + '12'
        res.update(start_date=date_start, end_date=date_end)
        return res

    @api.multi
    def action_show_expense(self):
        value = self.env['expense.line'].show_expense_lines(self.start_date,
                                                            self.end_date)
        return value


class ExpenseLine(models.TransientModel):
    _name = 'expense.line'

    name = fields.Char('Concept')
    sales = fields.Float('Sales')
    cost = fields.Float('Costs')
    margin = fields.Float('Margin')
    cost_per = fields.Float('% Costs')
    margin_per = fields.Float('% Margin')
    totalizator = fields.Boolean('Totalizator')
    compute_type = fields.Selection(COMPUTE_TYPES, 'Compute Type',
                                    required=True,
                                    readonly=True,
                                    default='analytic')

    @api.model
    def show_expense_lines(self, date_start, date_end):
        line_ids = []
        res = {}
        if not self._context.get('active_id', False):
            return res
        partner = self.env['res.partner'].browse(self._context['active_id'])
        if not partner.structure_id:
            raise except_orm(_('Error'), ('No expense structure founded.'))

        line_values_lst = self._compute_line_values(partner, date_start,
                                                    date_end)
        line_ids = self._create_expense_lines(line_values_lst)
        res = {
            'domain': str([('id', 'in', line_ids)]),
            'view_type': 'tree',
            'view_mode': 'tree',
            'res_model': 'expense.line',
            'type': 'ir.actions.act_window',
            'nodestroy': True
        }
        return res

    @api.model
    def _compute_line_values(self, partner, start_date, end_date):
        res = {}
        values = []
        sales = 0.0
        last_margin = 0.0  # last line
        first = True
        for e in partner.structure_id.element_ids:
            v = {
                'name': e.expense_type_id.name,
                'sales': 0.0,
                'cost': 0.0,
                'margin': 0.0,
                'cost_per': 0.0,
                'margin_per': 0.0,
                'compute_type': e.compute_type
            }
            # Calcule expense amount
            amount = 0.0
            if e.compute_type == 'analytic':
                amount = self._analytic_compute_amount(e, partner, start_date,
                                                       end_date)
            elif e.compute_type == 'ratio':
                parent_id = e.parent_id.id
                if res.get(parent_id, False):
                    amount = res[parent_id]['cost'] * e.ratio
            elif e.compute_type in ['total_cost', 'total_margin']:
                if e.compute_type == 'total_cost':
                    v['cost'] = self._totalizator(values, 'cost')
                    v['cost_per'] = (v['cost'] / (sales or 1.0)) * 100
                else:
                    v['margin'] = self._totalizator(values, 'margin')
                    v['margin_per'] = (v['margin'] / (sales or 1.0)) * 100
                res[e.id] = v
                values.append(v)
                continue

            # Calcule columns
            if first:  # First time
                first = False
                v['sales'] = last_margin = sales = amount * (-1)
            else:
                v['cost'] = amount if amount else 0.0

            v['margin'] = last_margin - v['cost']
            v['cost_per'] = (v['cost'] / (sales or 1.0)) * 100
            if e.compute_type == 'ratio':
                v['cost_per'] = e.ratio
            v['margin_per'] = (v['sales'] / (sales or 1.0)) * 100
            last_margin = v['margin']

            # Adds result to final order list an aux dictionary
            res[e.id] = v
            values.append(v)
        print res
        return values

    def _analytic_compute_amount(self, e, partner, start_date, end_date):
        res = 0.0

        aac = self.env['account.analytic.account'].\
            search([('partner_id', '=', partner.id)], limit=1)
        if not aac:
            return 0.0

        journal_id = e.expense_type_id.journal_id.id
        query = """
            SELECT sum(amount)
            FROM account_analytic_line
            WHERE journal_id = %s AND account_id = %s AND
                  date >= '%s' AND date <= '%s'
        """ % (str(journal_id), str(aac.id), start_date, end_date)
        self._cr.execute(query)
        qres = self._cr.fetchall()
        if not qres:
            return 0.0
        print "QRES "
        print qres
        res = qres[0][0] if qres[0][0] is not None else 0.0
        return res * (-1)

    def _totalizator(self, values, mode):
        total = 0.0
        for v in values:
            if v['compute_type'] in ['total_cost', 'total_margin']:
                continue
            if mode == 'cost':
                total += v['cost']
            else:
                total += v['margin']
        return total

    @api.model
    def _create_expense_lines(self, line_values):
        res = []
        for v in line_values:
            vals = {
                'name': v['name'],
                'compute_type': v['compute_type'],
                'sales': round(v['sales'], 2),
                'cost': round(v['cost'], 2),
                'margin': round(v['margin'], 2),
                'cost_per': round(v['cost_per'], 2),
                'margin_per': round(v['margin_per'], 2),
            }
            expense_line = self.create(vals)
            res.append(expense_line.id)
        return res