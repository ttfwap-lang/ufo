import pywinauto
from pywinauto import Application

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

# Find the MainWidget and explore
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

# Find MainWidget
main_widget = find_by_class(win, 'MainWidget')
if main_widget:
    print(f"Found MainWidget: {main_widget.class_name()}")
    print("Children:")
    for child in main_widget.children():
        print(f"  {child.class_name()} | {child.element_info.control_type} | auto_id={child.element_info.automation_id} | name={child.window_text()[:80]}")

# Find Dialogs::Widget
dialogs_widget = find_by_class(win, 'Dialogs::Widget')
if dialogs_widget:
    print(f"\nFound Dialogs::Widget: {dialogs_widget.class_name()}")
    print("Children:")
    for child in dialogs_widget.children():
        print(f"  {child.class_name()} | {child.element_info.control_type} | auto_id={child.element_info.automation_id} | name={child.window_text()[:80]}")
        # Go one level deeper
        for grandchild in child.children():
            print(f"    {grandchild.class_name()} | {grandchild.element_info.control_type} | auto_id={grandchild.element_info.automation_id} | name={grandchild.window_text()[:80]}")
            # Go one more level
            for gg in grandchild.children():
                print(f"      {gg.class_name()} | {gg.element_info.control_type} | auto_id={gg.element_info.automation_id} | name={gg.window_text()[:80]}")

# Print full tree of RpWidget (max 4 levels)
print("\n=== RpWidget full tree (4 levels) ===")
rp = find_by_class(win, 'RpWidget')
def print_tree(element, max_depth=4, current_depth=0, prefix=""):
    if current_depth > max_depth:
        return
    try:
        name = element.window_text()[:80]
        ctrl_type = element.element_info.control_type
        auto_id = element.element_info.automation_id
        class_name = element.class_name()
        print(f'{prefix}{class_name} | {ctrl_type} | auto_id={auto_id} | name={name}')
    except Exception as e:
        print(f'{prefix}<error: {e}>')
    try:
        for child in element.children():
            print_tree(child, max_depth, current_depth + 1, prefix + "  ")
    except:
        pass

if rp:
    print_tree(rp, max_depth=4)