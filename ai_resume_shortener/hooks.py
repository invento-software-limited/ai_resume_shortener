app_name = "ai_resume_shortener"
app_title = "AI Resume Shortener"
app_publisher = "Invento Software Limited"
app_description = "Automate candidate resume screening, ATS scoring, and interview question generation for Frappe HR with multi-model AI failover and token cost tracking."
app_email = "hello@invento.com.bd"
app_license = "mit"
app_logo_url = "/assets/ai_resume_shortener/logo.png"

# Apps
# ------------------

required_apps = ["hrms"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "ai_resume_shortener",
# 		"logo": "/assets/ai_resume_shortener/logo.png",
# 		"title": "Ai Resume Shortener",
# 		"route": "/ai_resume_shortener",
# 		"has_permission": "ai_resume_shortener.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/ai_resume_shortener/css/ai_resume_shortener.css"
# app_include_js = "/assets/ai_resume_shortener/js/ai_resume_shortener.js"

# include js, css files in header of web template
# web_include_css = "/assets/ai_resume_shortener/css/ai_resume_shortener.css"
# web_include_js = "/assets/ai_resume_shortener/js/ai_resume_shortener.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "ai_resume_shortener/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"Job Applicant": "public/js/job_applicant.js"}
doctype_list_js = {"Job Applicant": "public/js/job_applicant_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "ai_resume_shortener/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "ai_resume_shortener.utils.jinja_methods",
# 	"filters": "ai_resume_shortener.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "ai_resume_shortener.install.before_install"
# after_install = "ai_resume_shortener.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "ai_resume_shortener.uninstall.before_uninstall"
# after_uninstall = "ai_resume_shortener.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "ai_resume_shortener.utils.before_app_install"
# after_app_install = "ai_resume_shortener.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "ai_resume_shortener.utils.before_app_uninstall"
# after_app_uninstall = "ai_resume_shortener.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "ai_resume_shortener.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

after_migrate = "ai_resume_shortener.ai_resume_shortener.utils.after_migrate.create_ai_provider_list"

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.resume_analysis_scheduler",
	]
}
# scheduler_events = {
# 	"all": [
# 		"ai_resume_shortener.tasks.all"
# 	],
# 	"daily": [
# 		"ai_resume_shortener.tasks.daily"
# 	],
# 	"hourly": [
# 		"ai_resume_shortener.tasks.hourly"
# 	],
# 	"weekly": [
# 		"ai_resume_shortener.tasks.weekly"
# 	],
# 	"monthly": [
# 		"ai_resume_shortener.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "ai_resume_shortener.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "ai_resume_shortener.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "ai_resume_shortener.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "ai_resume_shortener.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["ai_resume_shortener.utils.before_request"]
# after_request = ["ai_resume_shortener.utils.after_request"]

# Job Events
# ----------
# before_job = ["ai_resume_shortener.utils.before_job"]
# after_job = ["ai_resume_shortener.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"ai_resume_shortener.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


fixtures = [
	{"dt": "Workspace", "filters": [["module", "=", "Ai Resume Shortener"]]},
]
