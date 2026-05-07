from ouroboros.tool_capabilities import CORE_TOOL_NAMES, READ_ONLY_PARALLEL_TOOLS, TOOL_RESULT_LIMITS


def test_pulse_people_search_is_core_parallel_and_has_limit():
    assert "pulse_people_search" in CORE_TOOL_NAMES
    assert "pulse_people_search" in READ_ONLY_PARALLEL_TOOLS
    assert TOOL_RESULT_LIMITS["pulse_people_search"] == 120_000
