"""odv tools: bring Archicad and Rhino models into Blender for rendering.

Each tool is a module with its own register() and unregister(),
and draws its panel in the 3D Viewport sidebar, on the odv tab.
"""

from .archicad import fbx_model_update
from .blender import material_id

modules = (fbx_model_update, material_id)


def register():
    for module in modules:
        module.register()


def unregister():
    for module in reversed(modules):
        module.unregister()
