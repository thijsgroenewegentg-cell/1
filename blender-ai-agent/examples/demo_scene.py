"""
Verification scene for the AI Agent Bridge.

With the server running in Blender (AI Agent tab > Start), run:

    python agent.py --exec examples/demo_scene.py

Blender should immediately show a small house with a roof, door, grass,
sun light and a camera - no LLM required, just to prove the bridge works.
"""

import bpy
from mathutils import Vector


# --- wipe the default scene ------------------------------------------------
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
              bpy.data.cameras, bpy.data.lights):
    for item in list(block):
        block.remove(item)


def make_material(name, color, roughness=0.6, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def point_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


# --- ground ----------------------------------------------------------------
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "Ground"
ground.data.materials.append(make_material("Grass", (0.18, 0.42, 0.14), 0.95))

# --- house body -------------------------------------------------------------
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
house = bpy.context.active_object
house.name = "House"
house.scale = (1.2, 1.0, 0.8)
house.data.materials.append(make_material("Walls", (0.85, 0.76, 0.6), 0.85))

# --- roof (4-sided cone = pyramid) -----------------------------------------
bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=1.9, depth=1.4,
                                location=(0, 0, 2.45), rotation=(0, 0, 0.7854))
roof = bpy.context.active_object
roof.name = "Roof"
roof.scale = (1.28, 1.08, 1.0)
roof.data.materials.append(make_material("RoofTiles", (0.55, 0.12, 0.08), 0.7))

# --- door -------------------------------------------------------------------
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -1.02, 0.6))
door = bpy.context.active_object
door.name = "Door"
door.scale = (0.32, 0.02, 0.6)
door.data.materials.append(make_material("DoorWood", (0.32, 0.18, 0.07), 0.5))

# --- sun --------------------------------------------------------------------
bpy.ops.object.light_add(type='SUN', location=(4, -4, 8))
sun = bpy.context.active_object
sun.name = "Sun"
sun.data.energy = 2.8
sun.rotation_euler = (0.7, 0.3, 0.8)

# --- camera -----------------------------------------------------------------
bpy.ops.object.camera_add(location=(6.5, -6.5, 4.5))
cam = bpy.context.active_object
cam.name = "Camera"
bpy.context.scene.camera = cam
point_at(cam, (0, 0, 1))

# --- world + render settings ------------------------------------------------
scene = bpy.context.scene
scene.world.use_nodes = True
bg = scene.world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.55, 0.72, 0.95, 1.0)
bg.inputs["Strength"].default_value = 0.9

try:
    scene.render.engine = 'BLENDER_EEVEE_NEXT'   # Blender 4.2+
except TypeError:
    scene.render.engine = 'BLENDER_EEVEE'        # Blender 3.x / 4.0/4.1

print("Demo scene built with %d objects: %s"
      % (len(scene.objects), [o.name for o in scene.objects]))
