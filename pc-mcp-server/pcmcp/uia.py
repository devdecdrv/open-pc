"""UI Automation helpers (text view of the screen + click by element name). Needs `uiautomation`."""
INTERACTIVE = {"ButtonControl", "EditControl", "CheckBoxControl", "ComboBoxControl", "HyperlinkControl",
               "ListItemControl", "MenuItemControl", "TabItemControl", "RadioButtonControl", "TreeItemControl"}


def _auto():
    import uiautomation as auto
    return auto


def _describe(c):
    r = c.BoundingRectangle
    return {"name": (c.Name or "")[:80], "type": c.ControlTypeName.replace("Control", ""),
            "x": (r.left + r.right) // 2, "y": (r.top + r.bottom) // 2,
            "rect": [r.left, r.top, r.right, r.bottom]}


def _walk(ctrl, depth, max_depth, limit, out, pred):
    if len(out) >= limit or depth > max_depth:
        return
    try:
        children = ctrl.GetChildren()
    except Exception:
        return
    for c in children:
        if len(out) >= limit:
            return
        try:
            r = c.BoundingRectangle
            if (r.right - r.left) > 0 and (r.bottom - r.top) > 0 and not c.IsOffscreen and pred(c):
                out.append(c)
        except Exception:
            continue
        _walk(c, depth + 1, max_depth, limit, out, pred)


def read_screen(window_only=True, max_items=150, max_depth=14):
    auto = _auto()
    with auto.UIAutomationInitializerInThread(debug=False):
        root = auto.GetForegroundControl() if window_only else auto.GetRootControl()
        found = []
        _walk(root, 0, max_depth, max_items,
              found, lambda c: bool(c.Name) or c.ControlTypeName in INTERACTIVE)
        return {"window": (root.Name or "")[:120], "items": [_describe(c) for c in found]}


def find(name, control_type=None, exact=False, window_only=True, limit=5):
    auto = _auto()
    needle = name.lower()

    def pred(c):
        n = (c.Name or "").lower()
        ok = (n == needle) if exact else (needle in n)
        return ok and (not control_type or control_type.lower() in c.ControlTypeName.lower())

    with auto.UIAutomationInitializerInThread(debug=False):
        results = []
        roots = [auto.GetForegroundControl()] if window_only else []
        roots.append(auto.GetRootControl())
        for root in roots:
            _walk(root, 0, 16, limit, results, pred)
            if results:
                break
        return [_describe(c) for c in results]
