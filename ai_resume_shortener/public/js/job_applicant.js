frappe.ui.form.on("Job Applicant", {
	refresh(frm) {
		if (!frm.is_new()) {
			// Primary Action Button: Instant AI Analysis
			frm.add_custom_button(__("Analyze with AI"), function () {
				frappe.call({
					method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.analyze_single_applicant",
					args: {
						job_applicant_name: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Evaluating resume with AI model..."),
					callback: function (r) {
						if (r.message && r.message.status === "success") {
							frappe.show_alert({
								title: __("Analysis Completed"),
								indicator: "green",
								message: __("AI resume evaluation completed successfully!"),
							});
							frm.reload_doc();
						} else {
							frappe.msgprint({
								title: __("Analysis Failed"),
								indicator: "red",
								message: r.message
									? r.message.reason
									: __("Could not analyze resume."),
							});
							frm.reload_doc();
						}
					},
				});
			});

			// Actions Group Sub-items
			frm.add_custom_button(
				__("Enqueue Background Job"),
				function () {
					frappe.call({
						method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.enqueue_single_applicant_analysis",
						args: {
							job_applicant_name: frm.doc.name,
						},
						freeze: true,
						freeze_message: __("Enqueuing background job..."),
						callback: function (r) {
							if (r.message && r.message.status === "enqueued") {
								frappe.show_alert({
									title: __("Enqueued"),
									indicator: "green",
									message: __("Analysis job queued in background worker!"),
								});
								frm.reload_doc();
							} else {
								frappe.msgprint({
									title: __("Enqueue Failed"),
									indicator: "red",
									message: r.message
										? r.message.reason
										: __("Failed to enqueue job."),
								});
							}
						},
					});
				},
				__("Actions")
			);

			frm.add_custom_button(
				__("Benchmark Models"),
				function () {
					frappe.call({
						method: "ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.benchmark_resume",
						args: { job_applicant_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Running AI benchmark across models..."),
						callback: function (r) {
							if (r.message && r.message.benchmark) {
								let rows = r.message.benchmark
									.map(
										(b) => `
								<tr>
									<td><b>${b.provider}</b></td>
									<td>${b.model_name}</td>
									<td>${b.execution_time_sec}s</td>
									<td>${b.total_tokens}</td>
									<td>$${b.estimated_cost_usd}</td>
									<td>${b.overall_score}/100</td>
									<td><span class="badge badge-info">${b.recommendation}</span></td>
								</tr>
							`
									)
									.join("");

								let html = `
								<table class="table table-bordered table-striped">
									<thead>
										<tr>
											<th>Provider</th>
											<th>Model</th>
											<th>Latency</th>
											<th>Tokens</th>
											<th>Cost</th>
											<th>Score</th>
											<th>Recommendation</th>
										</tr>
									</thead>
									<tbody>${rows}</tbody>
								</table>
							`;

								let d = new frappe.ui.Dialog({
									title: __("AI Model Benchmark Comparison"),
									size: "large",
									fields: [
										{
											fieldtype: "HTML",
											fieldname: "benchmark_html",
											options: html,
										},
									],
								});
								d.show();
							}
						},
					});
				},
				__("Actions")
			);
		}
	},
});
