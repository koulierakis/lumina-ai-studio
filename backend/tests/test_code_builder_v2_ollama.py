from code_builder_v2.models import TaskRequest
from code_builder_v2.ollama import OllamaChangeGenerator, OllamaPlanner


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_json(self, prompt, model=None):
        return self.responses.pop(0)


def test_ollama_planner_parses_structured_plan():
    client = FakeClient([{"summary":"x","changes":[{"path":"a.py","operation":"create","reason":"needed"}],"validation_commands":["pytest -q"]}])
    plan = OllamaPlanner(client).create_plan(TaskRequest(prompt="create a.py"))
    assert plan.changes[0].path == "a.py"


def test_ollama_generator_returns_full_file_changes():
    client = FakeClient([{"changes":[{"path":"a.py","operation":"create","content":"x = 1\n"}]}])
    planner = OllamaPlanner(FakeClient([{"summary":"x","changes":[{"path":"a.py","operation":"create","reason":"needed"}],"validation_commands":[]}]))
    request = TaskRequest(prompt="create a.py")
    plan = planner.create_plan(request)
    changes = OllamaChangeGenerator(client).generate(request, plan, {})
    assert changes[0].content == "x = 1\n"
