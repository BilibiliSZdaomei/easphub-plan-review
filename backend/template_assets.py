from pathlib import Path


_DIRECTORY = Path(__file__).parent / "templates"
WORKBOOK_TEMPLATES = {
    "plan": (_DIRECTORY / "replenishment-plan.xlsx", "补货计划模板.xlsx"),
    "v2": (_DIRECTORY / "plan-review-v2.xlsx", "计划审核V2模板.xlsx"),
}
