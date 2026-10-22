# Evaluation protocol

Do not report results until experiments have actually been run. Suggested CSV columns:
`headline,article_text,reference_summary,generated_summary,image_prompt,image_path,summary_provider,image_provider,summary_human_rating,image_relevance_rating,image_quality_rating,latency_ms,cost`

Prepare a permitted dataset, record model/provider configuration, compute ROUGE only where reference summaries exist, collect human ratings with a defined rubric, record latency/failures, and separate demo output from real model output. Do not fabricate metrics.
