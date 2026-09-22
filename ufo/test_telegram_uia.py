import pywinauto
from pywinauto import Application

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

# Find the message input area
def find_by_name(element, target_name, max_depth=5, current_depth=0):
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

# Search for common input-related names
for term in ['message', 'input', 'type', 'edit', 'text', 'compose', 'send']:
    result = find_by_name(win, term)
    if result:
        print(f'Found "{term}": {result.class_name()} | {result.element_info.control_type} | {result.window_text()[:100]}')

# Also print all Edit controls
print("\n=== All Edit controls ===")
def find_edits(element, max_depth=5, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        if element.element_info.control_type == 'Edit':
            print(f'  Edit: {element.class_name()} | {element.window_text()[:100]} | auto_id={element.element_info.automation_id}')
    except:
        pass
    try:
        for child in element.children():
            find_edits(child, max_depth, current_depth + 1)
    except:
        pass

find_edits(win)

# Print all Button controls
print("\n=== All Button controls ===")
def find_buttons(element, max_depth=5, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        if element.element_info.control_type == 'Button':
            print(f'  Button: {element.class_name()} | {element.window_text()[:100]} | auto_id={element.element_info.automation_id}')
    except:
        pass
    try:
        for child in element.children():
            find_buttons(child, max_depth, current_depth + 1)
    except:
        pass

find_buttons(win)

# Print all List controls (message area)
print("\n=== All List controls ===")
def find_lists(element, max_depth=5, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        if element.element_info.control_type == 'List':
            print(f'  List: {element.class_name()} | {element.window_text()[:100]} | auto_id={element.element_info.automation_id}')
            # Print first few items
            for i, child in enumerate(element.children()[:3]):
                print(f'    Item {i}: {child.class_name()} | {child.element_info.control_type} | {child.window_text()[:100]}')
    except:
        pass
    try:
        for child in element.children():
            find_lists(child, max_depth, current_depth + 1)
    except:
        pass

find_lists(win)