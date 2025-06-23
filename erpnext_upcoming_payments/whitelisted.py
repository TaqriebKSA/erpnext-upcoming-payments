import frappe
from frappe import _
import json
from six import string_types
import os
from frappe.monitor import add_data_to_monitor
from frappe.utils import sbool

@frappe.whitelist()
@frappe.read_only()
def run(
	report_name,
	filters=None,
	user=None,
	ignore_prepared_report=False,
	custom_columns=None,
	is_tree=False,
	parent_field=None,
	are_default_filters=True,
):
	from frappe.desk.query_report import get_report_doc, get_prepared_report_result, generate_report_result,validate_filters_permissions

	if not user:
		user = frappe.session.user
	validate_filters_permissions(report_name, filters, user)
	report = get_report_doc(report_name)
	if not frappe.has_permission(report.ref_doctype, "report"):
		frappe.msgprint(
			_("Must have report permission to access this report."),
			raise_exception=True,
		)

	result = None
	# custom code for overriding native reports
	try:
		from erpnext_upcoming_payments.override_reports import reports
		reports.main(report_name)
	except:
		pass

	if sbool(are_default_filters) and report.get("custom_filters"):
		filters = report.custom_filters

	try:
		if report.prepared_report and not sbool(ignore_prepared_report) and not custom_columns:
			if filters:
				if isinstance(filters, str):
					filters = json.loads(filters)

				dn = filters.pop("prepared_report_name", None)
			else:
				dn = ""
			result = get_prepared_report_result(report, filters, dn, user)
		else:
			result = generate_report_result(report, filters, user, custom_columns, is_tree, parent_field)
			add_data_to_monitor(report=report.reference_report or report.name)
	except Exception:
		frappe.log_error("Report Error")
		raise

	result["add_total_row"] = report.add_total_row and not result.get("skip_total_row", False)

	if sbool(are_default_filters) and report.get("custom_filters"):
		result["custom_filters"] = report.custom_filters

	return result

@frappe.whitelist()
def get_script(report_name):
	from frappe.desk.query_report import get_report_doc
	from frappe.modules import scrub, get_module_path
	from frappe.utils import get_html_format
	from frappe.model.utils import render_include
	from frappe.translate import send_translations


	report = get_report_doc(report_name)
	module = report.module or frappe.db.get_value("DocType", report.ref_doctype, "module")

	is_custom_module = frappe.get_cached_value("Module Def", module, "custom")

	# custom modules are virtual modules those exists in DB but not in disk.
	module_path = "" if is_custom_module else get_module_path(module)
	report_folder = module_path and os.path.join(module_path, "report", scrub(report.name))
	script_path = report_folder and os.path.join(report_folder, scrub(report.name) + ".js")
	print_path = report_folder and os.path.join(report_folder, scrub(report.name) + ".html")

	script = None

	# Customized code to override js of reports
	reports_script = frappe.get_hooks().get('app_reports_js', {})
	if reports_script and reports_script.get(report_name):
		script_path = frappe.get_app_path("erpnext_upcoming_payments", reports_script.get(report_name)[0])

	# Customized code to override default print format of reports
	# reports_print = frappe.get_hooks().get('app_reports_html', {})
	# if reports_print and reports_print.get(report_name):
	#     print_path = frappe.get_app_path("jawaerp", reports_print.get(report_name)[0])

	if os.path.exists(script_path):
		with open(script_path) as f:
			script = f.read()
			script += f"\n\n//# sourceURL={scrub(report.name)}.js"

	html_format = get_html_format(print_path)

	if not script and report.javascript:
		script = report.javascript
		script += f"\n\n//# sourceURL={scrub(report.name)}__custom"

	if not script:
		script = "frappe.query_reports['%s']={}" % report_name

	return {
		"script": render_include(script),
		"html_format": html_format,
		"execution_time": frappe.cache.hget("report_execution_time", report_name) or 0,
		"filters": report.filters,
		"custom_report_name": report.name if report.get("is_custom_report") else None,
	}
