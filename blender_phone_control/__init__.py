bl_info = {
    "name": "Phone Control",
    "author": "khattak-k",
    "version": (0, 1, 0),
    "blender": (3, 3, 0),
    "location": "3D Viewport > Sidebar (N) > Phone",
    "description": "Control Blender from your phone over the local network via a touch-friendly web UI",
    "category": "Interface",
}

import bpy

from . import bridge, server, ops


class PhoneControlPrefs(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: bpy.props.IntProperty(
        name="Port", default=8765, min=1024, max=65535,
        description="TCP port the phone connects to",
    )
    autostart: bpy.props.BoolProperty(
        name="Start server when Blender opens", default=False,
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "port")
        col.prop(self, "autostart")
        col.label(text="Windows: allow python.exe / blender.exe through the firewall on Private networks.", icon="INFO")


class PHONE_OT_start(bpy.types.Operator):
    bl_idname = "phone_control.start"
    bl_label = "Start Server"
    bl_description = "Start listening for the phone on the local network"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        try:
            server.start(prefs.port)
        except OSError as e:
            self.report({"ERROR"}, f"Could not start server: {e}")
            return {"CANCELLED"}
        bridge.start()
        self.report({"INFO"}, f"Phone Control listening on port {prefs.port}")
        return {"FINISHED"}


class PHONE_OT_stop(bpy.types.Operator):
    bl_idname = "phone_control.stop"
    bl_label = "Stop Server"

    def execute(self, context):
        server.stop()
        bridge.stop()
        return {"FINISHED"}


class PHONE_OT_new_pin(bpy.types.Operator):
    bl_idname = "phone_control.new_pin"
    bl_label = "New PIN"
    bl_description = "Invalidate all connected phones and generate a fresh PIN"

    def execute(self, context):
        server.rotate_pin()
        return {"FINISHED"}


class PHONE_OT_clear_chat(bpy.types.Operator):
    bl_idname = "phone_control.clear_chat"
    bl_label = "Clear Chat"
    bl_description = "Forget the phone/Claude chat history"

    def execute(self, context):
        server.clear_messages()
        return {"FINISHED"}


class PHONE_PT_panel(bpy.types.Panel):
    bl_label = "Phone Control"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Phone"

    def draw(self, context):
        layout = self.layout
        status = server.status()
        if status["running"]:
            layout.label(text="Server: running", icon="CHECKMARK")
            box = layout.box()
            box.label(text="Open on your phone:")
            for ip in status["addresses"]:
                box.label(text=f"http://{ip}:{status['port']}")
            box.separator()
            box.label(text=f"PIN: {status['pin']}", icon="LOCKED")
            row = layout.row()
            row.operator("phone_control.stop", icon="PAUSE")
            row.operator("phone_control.new_pin", icon="FILE_REFRESH")
            layout.label(text=f"Connected phones: {status['sessions']}")
            if status["claude_online"]:
                layout.label(text="Claude: listening", icon="CHECKMARK")
            else:
                layout.label(text="Claude: not listening (claude_relay.py watch)", icon="ERROR")
            row = layout.row()
            row.label(text=f"Chat messages: {status['messages']}")
            row.operator("phone_control.clear_chat", text="", icon="TRASH")
        else:
            layout.label(text="Server: stopped", icon="X")
            layout.operator("phone_control.start", icon="PLAY")


classes = (PhoneControlPrefs, PHONE_OT_start, PHONE_OT_stop, PHONE_OT_new_pin, PHONE_OT_clear_chat, PHONE_PT_panel)


def _autostart():
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        if prefs.autostart and not server.status()["running"]:
            server.start(prefs.port)
            bridge.start()
    except Exception as e:  # never block Blender startup
        print("[Phone Control] autostart failed:", e)
    return None


def _refresh_panel():
    """Redraw the sidebar every few seconds so 'Claude: listening' stays current."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass
    return 5.0


def register():
    for c in classes:
        bpy.utils.register_class(c)
    ops.register_handlers()
    bpy.app.timers.register(_autostart, first_interval=1.0)
    bpy.app.timers.register(_refresh_panel, first_interval=5.0, persistent=True)


def unregister():
    server.stop()
    bridge.stop()
    ops.unregister_handlers()
    if bpy.app.timers.is_registered(_refresh_panel):
        bpy.app.timers.unregister(_refresh_panel)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
