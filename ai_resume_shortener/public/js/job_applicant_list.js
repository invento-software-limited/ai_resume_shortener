const esc = (value) => frappe.utils.escape_html(String(value ?? ""));

frappe.listview_settings["Job Applicant"] = {
	onload(listview) {
		// 1. Bulk Analyze Action
		listview.page.add_action_item(__("Analyze with AI"), function () {
			const selected_applicants = listview.get_checked_items().map((item) => item.name);
			if (!selected_applicants.length) {
				frappe.msgprint(__("Please select at least one Job Applicant."));
				return;
			}

			frappe.confirm(
				__(
					"Are you sure you want to enqueue AI resume analysis for {0} selected applicant(s)?",
					[selected_applicants.length]
				),
				function () {
					frappe.call({
						method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.enqueue_bulk_applicant_analysis",
						args: {
							job_applicant_names: selected_applicants,
						},
						freeze: true,
						freeze_message: __("Enqueuing background analysis jobs..."),
						callback(r) {
							if (r.message && r.message.status === "enqueued") {
								frappe.show_alert({
									message: r.message.message || __("Enqueued AI analysis jobs!"),
									indicator: "green",
								});
								listview.refresh();
							} else {
								frappe.msgprint({
									title: __("Error"),
									indicator: "red",
									message: esc(
										r.message
											? r.message.message
											: __("Failed to enqueue jobs.")
									),
								});
							}
						},
					});
				}
			);
		});

		// 2. Candidate Rankings Action
		listview.page.add_inner_button(
			__("Candidate Rankings"),
			function () {
				frappe.call({
					method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.get_ranked_candidates",
					callback(r) {
						if (r.message) {
							let rows = r.message
								.map(
									(c) => `
							<tr>
								<td><b>#${esc(c.rank)}</b></td>
								<td>${esc(c.applicant_name)}</td>
								<td>${esc(c.job_title || "-")}</td>
								<td><span class="badge badge-success">${esc(c.custom_match_percentage || 0)}%</span></td>
								<td>${esc(c.custom_overall_score || 0)}/100</td>
								<td>${esc(c.custom_recommendation || "-")}</td>
							</tr>
						`
								)
								.join("");

							let html = `
							<table class="table table-bordered table-striped">
								<thead>
									<tr>
										<th>Rank</th>
										<th>Applicant</th>
										<th>Job Title</th>
										<th>Match %</th>
										<th>Score</th>
										<th>Recommendation</th>
									</tr>
								</thead>
								<tbody>
									${rows || '<tr><td colspan="6" class="text-center">No analyzed applicants found.</td></tr>'}
								</tbody>
							</table>
						`;

							let d = new frappe.ui.Dialog({
								title: __("Top Candidate Rankings"),
								size: "large",
								fields: [
									{
										fieldtype: "HTML",
										fieldname: "rankings_html",
										options: html,
									},
								],
							});
							d.show();
						}
					},
				});
			},
			__("AI Actions")
		);

		// 3. Queue Dashboard & Retry Center Action
		listview.page.add_inner_button(
			__("Queue Dashboard"),
			function () {
				frappe.call({
					method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.get_queue_metrics",
					callback(r) {
						if (r.message) {
							let m = r.message;
							let html = `
							<div class="row text-center" style="margin-bottom: 15px;">
								<div class="col-sm-3">
									<div class="well">
										<h3>${esc(m.pending)}</h3>
										<p class="text-muted">Pending</p>
									</div>
								</div>
								<div class="col-sm-3">
									<div class="well">
										<h3 class="text-success">${esc(m.completed)}</h3>
										<p class="text-muted">Completed</p>
									</div>
								</div>
								<div class="col-sm-3">
									<div class="well">
										<h3 class="text-danger">${esc(m.failed)}</h3>
										<p class="text-muted">Failed</p>
									</div>
								</div>
								<div class="col-sm-3">
									<div class="well">
										<h3>${esc(m.total_logs)}</h3>
										<p class="text-muted">Total Logs</p>
									</div>
								</div>
							</div>
						`;

							let d = new frappe.ui.Dialog({
								title: __("AI Processing Queue Dashboard"),
								fields: [
									{ fieldtype: "HTML", fieldname: "queue_html", options: html },
								],
								primary_action_label: __("Retry All Failed"),
								primary_action() {
									frappe.call({
										method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.retry_failed_applicants",
										callback(res) {
											frappe.show_alert({
												message: __(
													"Enqueued {0} failed applicant(s) for retry.",
													[res.message.enqueued_count]
												),
												indicator: "green",
											});
											d.hide();
											listview.refresh();
										},
									});
								},
							});
							d.show();
						}
					},
				});
			},
			__("AI Actions")
		);
	},
};
