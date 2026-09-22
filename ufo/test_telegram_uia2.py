import pywinauto
from pywinauto import Application

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

# Find RpWidget and explore deeper
def find_rpwidget(element, max_depth=3, current_depth=0):
    if current_depth > max_depth:
        return None
    try:
        if 'RpWidget' in element.class_name():
            return element
    except:
        pass
    try:
        for child in element.children():
            result = find_rpwidget(child, max_depth, current_depth + 1)
            if result:
                return result
    except:
        pass
    return None

rp = find_rpwidget(win)
if rp:
    print(f"Found RpWidget: {rp.class_name()}")
    print("Children:")
    for child in rp.children():
        print(f"  {child.class_name()} | {child.element_info.control_type} | auto_id={child.element_info.automation_id} | name={child.window_text()[:80]}")
        
        # Go one level deeper for each child
        for grandchild in child.children():
            print(f"    {grandchild.class_name()} | {grandchild.element_info.control_type} | auto_id={grandchild.element_info.automation_id} | name={grandchild.window_text()[:80]}")

# Also try to find elements by control_type directly
print("\n=== All elements with control_type List or Edit or Document ===")
def find_by_control_type(element, target_types, max_depth=5, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        if element.element_info.control_type in target_types:
            print(f'  {element.element_info.control_type}: {element.class_name()} | auto_id={element.element_info.automation_id} | name={element.window_text()[:100]}')
    except:
        pass
    try:
        for child in element.children():
            find_by_control_type(child, target_types, max_depth, current_depth + 1)
    except:
        pass

find_by_control_type(win, ['List', 'Edit', 'Document', 'Text', 'Pane', 'Tree', 'Table'], max_depth=6)