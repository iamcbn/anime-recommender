import json
import pandas as pd
from pathlib import Path

def generate_report(history_path=None, output_md=None):
    if history_path is None:
        data_dir_history = Path(__file__).resolve().parent.parent / "data" / "evaluation_history.jsonl"
        root_history = Path(__file__).resolve().parent.parent.parent / "evaluation_history.jsonl"
        history_path = data_dir_history if data_dir_history.exists() else root_history

    if output_md is None:
        output_md = Path(__file__).resolve().parent.parent / "data" / "evaluation_report.md"

    if not Path(history_path).exists():
        print(f"Error: {history_path} not found. Run evaluate_first_stage.py first.")
        return

    data = []
    with open(history_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not data:
        print("No data found in jsonl file.")
        return

    df = pd.DataFrame(data)
    
    # We want to compare the original baseline with the new enriched version
    iterations = df['iteration_name'].unique()
    
    report_lines = [
        "# RAG Pipeline Evaluation Report",
        "This report compares the retrieval performance across different embedding strategies.",
        ""
    ]

    for it in sorted(iterations):
        it_df = df[df['iteration_name'] == it]
        # Get the latest run for this iteration
        latest_run = it_df.iloc[-1]
        
        total = latest_run['total_queries']
        hit_in_first_stage = latest_run['hit_in_first_stage']
        hit_rate_pct = latest_run['hit_rate_pct']

        report_lines.extend([
            f"## Iteration: `{it}`",
            f"**Total Queries Evaluated:** {total}",
            "",
            "### Stage 1: Retrieval Hit Rate @ 100",
            f"- **Hit Rate:** {hit_rate_pct:.2f}% ({hit_in_first_stage}/{total})",
            "",
            "---"
        ])
        
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
        
    print(f"Report successfully generated and saved to {output_md}")

if __name__ == "__main__":
    generate_report()
