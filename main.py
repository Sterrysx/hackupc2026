from langchain_core.messages import HumanMessage
from Ai_Agent.graph import build_graph


def main():
    graph = build_graph()

    user_query = input("Ask the Digital Twin: ")

    initial_state = {
        "messages": [HumanMessage(content=user_query)],
        "run_identifier": "",
        "retrieved_telemetry": "",
        "final_report": "",
        "validation_attempts": 0,
    }

    result = graph.invoke(initial_state)

    report = result.get("final_report")

    print("\n" + "=" * 60)
    print("DIAGNOSTIC REPORT")
    print("=" * 60)
    if isinstance(report, dict):
        print(f"SEVERITY: {report.get('severity_indicator', 'N/A')}")
        print(f"\nGROUNDED TEXT:\n{report.get('grounded_text', 'N/A')}")
        print(f"\nEVIDENCE CITATION:\n{report.get('evidence_citation', 'N/A')}")
    else:
        print(report or "No report generated.")


if __name__ == "__main__":
    main()
