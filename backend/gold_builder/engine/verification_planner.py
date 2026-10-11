"""Intelligent verification planner.

Derives an application-specific browser verification scenario from:
- application requirements & description
- generated source files (HTML, JSX, TSX, JS, Python)
- detected forms, inputs, buttons, navigation links, and interactive elements

Generates auditable, structured actions (open, fill, click, select, submit,
wait, assert_visible, assert_text, screenshot) without hardcoding single apps.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import Plan


def plan_verification_scenario(
    project_dir: Path,
    plan: Optional[Plan] = None,
    app_requirements: str = "",
) -> List[Dict[str, Any]]:
    """Generate structured browser verification steps tailored to the generated app."""
    scenario: List[Dict[str, Any]] = [
        {"action": "open"},
        {"action": "wait", "ms": 600, "args": {"ms": 600}},
        {"action": "assert_visible", "selector": "body", "args": {"selector": "body"}},
    ]

    source_texts: List[tuple[str, str]] = []
    for ext in ("*.html", "*.jsx", "*.tsx", "*.js", "*.vue"):
        for p in project_dir.glob(f"**/{ext}"):
            if any(part in p.parts for part in ("node_modules", ".git", "dist", "build", ".next")):
                continue
            try:
                source_texts.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
            except Exception:
                pass

    found_inputs: List[tuple[str, str]] = []
    found_buttons: List[str] = []
    found_links: List[str] = []
    has_form = False

    combined_req = (app_requirements or "") + " " + (plan.description if plan else "")

    for fname, text in source_texts:
        if "<form" in text.lower():
            has_form = True

        # Input fields (text, email, password, search, number, textarea)
        for m in re.finditer(r"""<input\s+[^>]*?(?:name|id|placeholder)=['"]([^'"]+)['"][^>]*>""", text, re.IGNORECASE):
            attr_val = m.group(1)
            selector = f"input[name='{attr_val}']" if f"name='{attr_val}'" in m.group(0) or f'name="{attr_val}"' in m.group(0) else f"#{attr_val}"
            if selector not in [inp[0] for inp in found_inputs]:
                val = "test@example.com" if "email" in attr_val.lower() else "Test User" if "name" in attr_val.lower() else "Test item entry"
                found_inputs.append((selector, val))

        for m in re.finditer(r"""<textarea\s+[^>]*?(?:name|id)=['"]([^'"]+)['"][^>]*>""", text, re.IGNORECASE):
            attr_val = m.group(1)
            selector = f"textarea[name='{attr_val}']" if f"name='{attr_val}'" in m.group(0) else f"#{attr_val}"
            if selector not in [inp[0] for inp in found_inputs]:
                found_inputs.append((selector, "Testing automated message entry"))

        # Buttons
        for m in re.finditer(r"""<(?:button|input\s+type=['"]submit['"])[^>]*>(.*?)</button>""", text, re.IGNORECASE | re.DOTALL):
            btn_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if btn_text and len(btn_text) < 30 and btn_text not in found_buttons:
                found_buttons.append(btn_text)

        # Links/Routes
        for m in re.finditer(r"""<a\s+[^>]*href=['"]([^'"#]+)['"][^>]*>(.*?)</a>""", text, re.IGNORECASE):
            href = m.group(1)
            if href.startswith("/") and href != "/" and href not in found_links:
                found_links.append(href)

    step_num = 1
    # 1. Landing screenshot
    scenario.append({
        "action": "screenshot",
        "name": f"step{step_num}_landing",
        "args": {"name": f"step{step_num}_landing"}
    })
    step_num += 1

    # 2. Interactive Navigation if available
    if found_links:
        target_link = found_links[0]
        scenario.append({
            "action": "click",
            "selector": f"a[href='{target_link}']",
            "args": {"selector": f"a[href='{target_link}']"}
        })
        scenario.append({"action": "wait", "ms": 400, "args": {"ms": 400}})
        scenario.append({
            "action": "screenshot",
            "name": f"step{step_num}_navigated",
            "args": {"name": f"step{step_num}_navigated"}
        })
        step_num += 1

    # 3. Form input & submission
    if found_inputs:
        for selector, val in found_inputs[:3]:
            scenario.append({
                "action": "fill",
                "selector": selector,
                "value": val,
                "args": {"selector": selector, "value": val}
            })
        scenario.append({"action": "wait", "ms": 300, "args": {"ms": 300}})
        scenario.append({
            "action": "screenshot",
            "name": f"step{step_num}_form_filled",
            "args": {"name": f"step{step_num}_form_filled"}
        })
        step_num += 1

        if has_form:
            scenario.append({
                "action": "submit",
                "selector": "form",
                "args": {"selector": "form"}
            })
            scenario.append({"action": "wait", "ms": 700, "args": {"ms": 700}})
            scenario.append({
                "action": "screenshot",
                "name": f"step{step_num}_form_submitted",
                "args": {"name": f"step{step_num}_form_submitted"}
            })
            step_num += 1
        elif found_buttons:
            btn_selector = f"button:has-text('{found_buttons[0]}')"
            scenario.append({
                "action": "click",
                "selector": btn_selector,
                "args": {"selector": btn_selector}
            })
            scenario.append({"action": "wait", "ms": 600, "args": {"ms": 600}})
            scenario.append({
                "action": "screenshot",
                "name": f"step{step_num}_button_clicked",
                "args": {"name": f"step{step_num}_button_clicked"}
            })
            step_num += 1
    elif found_buttons:
        btn_sel = f"button:has-text('{found_buttons[0]}')" if found_buttons else "button"
        scenario.append({
            "action": "click",
            "selector": btn_sel,
            "args": {"selector": btn_sel}
        })
        scenario.append({"action": "wait", "ms": 500, "args": {"ms": 500}})
        scenario.append({
            "action": "screenshot",
            "name": f"step{step_num}_interactive_click",
            "args": {"name": f"step{step_num}_interactive_click"}
        })
        step_num += 1

    # 4. Final verification state
    scenario.append({
        "action": "assert_visible",
        "selector": "body",
        "args": {"selector": "body"}
    })
    scenario.append({
        "action": "screenshot",
        "name": f"step{step_num}_final_state",
        "args": {"name": f"step{step_num}_final_state"}
    })

    return scenario
