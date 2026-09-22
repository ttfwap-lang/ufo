import pywinauto
from pywinauto import Application
import time

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

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

# Find HistoryWidget and try to interact with it
history = find_by_class(win, 'HistoryWidget')
if history:
    print(f"HistoryWidget rect: {history.rectangle()}")
    
    # Try clicking in the center of HistoryWidget to focus it
    rect = history.rectangle()
    center_x = (rect.left + rect.right) // 2
    center_y = (rect.top + rect.bottom) // 2
    print(f"Center: ({center_x}, {center_y})")
    
    # Click to focus
    history.click_input(coords=(center_x - rect.left, center_y - rect.top))
    print("Clicked HistoryWidget center")
    time.sleep(0.5)
    
    # Try sending keys
    try:
        history.type_keys("Hello from UIA!", with_spaces=True)
        print("Sent keys to HistoryWidget")
    except Exception as e:
        print(f"Failed to send keys to HistoryWidget: {e}")
    
    # Check descendants again
    descendants = history.descendants()
    print(f"\nDescendants after focus: {len(descendants)}")
    for i, desc in enumerate(descendants[:30]):
        print(f"  {i}: {desc.class_name()} | {desc.element_info.control_type} | name={desc.window_text()[:100]}")

# Also try the Ui::RpWidget (the inner one in MainWidget)
rp_widget = find_by_class(win, 'MainWidget')
if rp_widget:
    # Find the inner RpWidget
    for child in rp_widget.children():
        if 'RpWidget' in child.class_name():
            print(f"\nFound inner RpWidget: {child.class_name()}")
            descendants = child.descendants()
            print(f"Descendants: {len(descendants)}")
            for i, desc in enumerate(descendants[:50]):
                print(f"  {i}: {desc.class_name()} | {desc.element_info.control_type} | name={desc.window_text()[:100]}")

# Try to find any element that might be the message input by looking at all elements
print("\n=== All elements with 'Input' or 'Message' or 'Text' in class name ===")
def find_by_class_name_contains(element, keywords, max_depth=8, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        class_name = element.class_name()
        for kw in keywords:
            if kw.lower() in class_name.lower():
                print(f"  {class_name} | {element.element_info.control_type} | auto_id={element.element_info.automation_id} | name={element.window_text()[:100]}")
    except:
        pass
    try:
        for child in element.children():
            find_by_class_name_contains(child, keywords, max_depth, current_depth + 1)
    except:
        pass

find_by_class_name_contains(win, ['Input', 'Message', 'Text', 'Edit', 'Compose', 'Reply'])