"""Exercise only the actual GTK custom-designer function with in-memory setup state."""
import ast
import json
import traceback
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

source = Path(__file__).parents[1] / 'bin/magnolie_setup_ui.py'
tree = ast.parse(source.read_text())
function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'request_design')
parent = Gtk.Dialog()
parent.show_all()
state = []
errors = []
report = {}


def bind(widget, text):
    widget.set_label(text)
    return widget


scope = dict(Gtk=Gtk, tr=lambda value: value, bind=bind, label=lambda text: Gtk.Label(label=text, xalign=0),
             entry=lambda text: Gtk.Entry(placeholder_text=text), dialog=parent,
             custom_name=Gtk.Entry(), custom_enabled=Gtk.CheckButton(), custom_modules=state,
             custom_modules_changed=[False], dynamic_choices=[], MAX_ITEM_LENGTH=120)
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)


def descendants(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from descendants(child)


def exercise():
    modal = next(w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.Dialog) and w is not parent)
    try:
        def add(text):
            next(w for w in descendants(modal) if isinstance(w, Gtk.Button) and w.get_label() == text).clicked()

        def choices():
            return [w for w in descendants(modal) if isinstance(w, Gtk.ComboBoxText)]

        add('Text block'); add('Tasks'); add('Appointments')
        note, task, appointment = [next(w for w in choices() if w.get_accessible().get_name() == title + ': Page')
                                   for title in ('Text block', 'Tasks', 'Appointments')]
        assert [w.get_active_id() for w in (note, task, appointment)] == ['left', 'right', 'right']
        task.set_active_id('left')
        focus = modal.get_focus()
        assert task.get_active_id() == 'left' and (focus is task or focus.is_ancestor(task))
        appointment.set_active_id('left')
        assert appointment.get_active_id() == 'right'
        add('Text block')
        assert len(choices()) == 4
        note.set_active_id('right')
        assert note.get_active_id() == 'left'
        add('Text block'); add('Tasks'); add('Appointments')
        assert len(choices()) == 4
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        positions = sorted(w.translate_coordinates(modal, 0, 0) for w in choices())
        widths = [w.get_allocated_width() for w in choices()]
        assert positions[0][0] == positions[1][0] < positions[2][0] == positions[3][0], positions
        assert max(widths) - min(widths) <= 1, widths
        bounds = modal.get_display().get_monitor_at_window(modal.get_window()).get_workarea()
        assert modal.get_size().width <= bounds.width and modal.get_size().height <= bounds.height
        scroll = next(w for w in descendants(modal) if isinstance(w, Gtk.ScrolledWindow))
        adjustment = scroll.get_vadjustment()
        assert adjustment.get_upper() <= adjustment.get_page_size(), 'avoidable scroll'
        report.update(size=list(modal.get_size()), positions=positions, widths=widths)
        modal.response(Gtk.ResponseType.OK)
    except Exception as error:
        errors.append(traceback.format_exc())
        modal.response(Gtk.ResponseType.CANCEL)
    return False


GLib.timeout_add(150, exercise)
scope['request_design'](None)
parent.destroy()
assert not errors, errors
assert len(state) == 4 and scope['custom_modules_changed'][0]
assert [item['page'] for item in state if item['type'] == 'notes'] == ['left', 'right']
print(json.dumps(report))
