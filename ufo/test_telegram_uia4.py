import pywinauto
from pywinauto import Application

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

# Find specific widgets
def find_by_class(element, target_class, max_depth=6, current_depth=0):
    if current_depth > max_depth:
        return None
    try:
        if target_class in element.class_name():
            return element
    except:
        pass
    try:
        for child in element.children():
            result = find_by_class(child, target_class, max_depth, current_depth + 1)
            if result:
                return result
    except:
        pass
    return None

# Explore HistoryWidget (message area)
history = find_by_class(win, 'HistoryWidget')
if history:
    print(f"Found HistoryWidget: {history.class_name()}")
    print("Children:")
    for child in history.children():
        print(f"  {child.class_name()} | {child.element_info.control_type} | auto_id={child.element_info.automation_id} | name={child.window_text()[:80]}")
        for grandchild in child.children():
            print(f"    {grandchild.class_name()} | {grandchild.element_info.control_type} | auto_id={grandchild.element_info.automation_id} | name={grandchild.window_text()[:80]}")
            for gg in grandchild.children():
                print(f"      {gg.class_name()} | {gg.element_info.control_type} | auto_id={gg.element_info.automation_id} | name={gg.window_text()[:80]}")

# Explore Dialogs::InnerWidget (chat list)
inner_widget = find_by_class(win, 'Dialogs::InnerWidget')
if inner_widget:
    print(f"\nFound Dialogs::InnerWidget: {inner_widget.class_name()}")
    print("Children (first 10):")
    for i, child in enumerate(inner_widget.children()[:10]):
        print(f"  {i}: {child.class_name()} | {child.element_info.control_type} | auto_id={child.element_info.automation_id} | name={child.window_text()[:100]}")
        for grandchild in child.children():
            print(f"    {grandchild.class_name()} | {grandchild.element_info.control_type} | auto_id={grandchild.element_info.automation_id} | name={grandchild.window_text()[:100]}")

# Also look for message input area in HistoryWidget or nearby
print("\n=== Looking for message input / compose area ===")
def find_by_name(element, target_name, max_depth=6, current_depth=0):
    if current_depth > max_depth:
        return None
    try:
        if target_name.lower() in (element.window_text() or '').lower():
            return element
    except:
        pass
    try:
        for child in element.children():
            result = find_by_name(child, target_name, max_depth, current_depth + 1)
            if result:
                return result
    except:
        pass
    return None

# Search in whole window for message-related elements
for term in ['message', 'type', 'compose', 'input', 'edit', 'reply']:
    result = find_by_name(win, term)
    if result:
        print(f'Found "{term}": {result.class_name()} | {result.element_info.control_type} | auto_id={result.element_info.automation_id} | name={result.window_text()[:100]}')

# Look for all Edit controls in the whole window
print("\n=== All Edit controls (full tree) ===")
def find_all_edits(element, max_depth=8, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        if element.element_info.control_type == 'Edit':
            print(f'  Edit: {element.class_name()} | auto_id={element.element_info.automation_id} | name={element.window_text()[:100]}')
    except:
        pass
    try:
        for child in element.children():
            find_all_edits(child, max_depth, current_depth + 1)
    except:
        pass

find_all_edits(win)