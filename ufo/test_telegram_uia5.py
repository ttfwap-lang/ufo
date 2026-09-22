import pywinauto
from pywinauto import Application

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

# Find HistoryWidget
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

history = find_by_class(win, 'HistoryWidget')
if history:
    print(f"HistoryWidget: {history.class_name()}")
    print(f"  rect: {history.rectangle()}")
    print(f"  control_type: {history.element_info.control_type}")
    print(f"  has_keyboard_focus: {history.has_keyboard_focus()}")
    print(f"  is_enabled: {history.is_enabled()}")
    print(f"  is_visible: {history.is_visible()}")
    
    # Try to get all descendant elements using descendants()
    print("\n=== All descendants of HistoryWidget ===")
    try:
        descendants = history.descendants()
        for i, desc in enumerate(descendants[:50]):
            print(f"  {i}: {desc.class_name()} | {desc.element_info.control_type} | auto_id={desc.element_info.automation_id} | name={desc.window_text()[:100]}")
    except Exception as e:
        print(f"Error getting descendants: {e}")

    # Try using element_info.children
    print("\n=== Using element_info.children ===")
    try:
        children = history.element_info.children
        for i, child in enumerate(children[:20]):
            print(f"  {i}: {child.class_name} | {child.control_type} | auto_id={child.automation_id} | name={child.name}")
    except Exception as e:
        print(f"Error: {e}")

# Let's also try to click on a chat and see what appears
inner_widget = find_by_class(win, 'Dialogs::InnerWidget')
if inner_widget:
    print(f"\n=== Dialogs::InnerWidget (chat list) - clicking first chat ===")
    chats = inner_widget.children()
    if chats:
        first_chat = chats[0]
        print(f"First chat: {first_chat.class_name()} | {first_chat.element_info.control_type} | name={first_chat.window_text()[:100]}")
        try:
            first_chat.click_input()
            print("Clicked first chat")
            import time
            time.sleep(1)
            
            # Now check HistoryWidget again
            history2 = find_by_class(win, 'HistoryWidget')
            if history2:
                print("\n=== HistoryWidget after click ===")
                descendants = history2.descendants()
                for i, desc in enumerate(descendants[:50]):
                    print(f"  {i}: {desc.class_name()} | {desc.element_info.control_type} | auto_id={desc.element_info.automation_id} | name={desc.window_text()[:100]}")
        except Exception as e:
            print(f"Error clicking: {e}")

# Also look for the message input area after selecting a chat
print("\n=== All Edit controls after potential chat selection ===")
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