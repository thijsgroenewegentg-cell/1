# SPDX-License-Identifier: MIT
"""
Scene-template presets: opinionated lighting/camera/world baselines the agent
can apply in one call so renders start from a good setup. Each preset is
self-contained bpy code; it uses helpers where helpful but inlines everything
so it works on any transport.
"""

PRESETS = {
    "product": {
        "label": "Product render (white sweep, softbox, orbit camera)",
        "code": r'''
import bpy, math
from mathutils import Vector

# neutral white studio world
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.9, 0.9, 0.92, 1)
bg.inputs["Strength"].default_value = 0.6

# white ground plane (acts as a sweep)
if not bpy.data.objects.get("StudioFloor"):
    bpy.ops.mesh.primitive_plane_add(size=30)
    floor = bpy.context.active_object
    floor.name = "StudioFloor"
    mat = bpy.data.materials.new("StudioWhite")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.95, 0.95, 0.95, 1)
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.4
    floor.data.materials.append(mat)

def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# key softbox
if not bpy.data.objects.get("KeySoftbox"):
    bpy.ops.object.light_add(type='AREA', location=(4, -4, 6))
    key = bpy.context.active_object; key.name = "KeySoftbox"
    key.data.energy = 900; key.data.size = 4
    look_at(key, (0, 0, 1))
if not bpy.data.objects.get("FillSoftbox"):
    bpy.ops.object.light_add(type='AREA', location=(-5, -1, 3))
    fill = bpy.context.active_object; fill.name = "FillSoftbox"
    fill.data.energy = 300; fill.data.size = 6
    fill.data.color = (0.85, 0.9, 1.0)
    look_at(fill, (0, 0, 1))
if not bpy.data.objects.get("RimLight"):
    bpy.ops.object.light_add(type='AREA', location=(0, 5, 4))
    rim = bpy.context.active_object; rim.name = "RimLight"
    rim.data.energy = 500; rim.data.size = 3
    look_at(rim, (0, 0, 1))

# camera
if not bpy.data.objects.get("ProductCamera"):
    bpy.ops.object.camera_add(location=(5.5, -5.5, 3.2))
    cam = bpy.context.active_object; cam.name = "ProductCamera"
    cam.data.lens = 70
    look_at(cam, (0, 0, 0.8))
    bpy.context.scene.camera = cam

for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
    try:
        bpy.context.scene.render.engine = eng; break
    except TypeError: pass
bpy.context.scene.render.resolution_x = 1200
bpy.context.scene.render.resolution_y = 1200
print("Preset 'product' applied.")
''',
    },

    "archviz": {
        "label": "Architectural viz (sun through window, warm interior)",
        "code": r'''
import bpy
from mathutils import Vector
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.75, 0.82, 0.95, 1)
bg.inputs["Strength"].default_value = 0.8

def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

if not bpy.data.objects.get("Sun"):
    bpy.ops.object.light_add(type='SUN', location=(6, -6, 9))
    sun = bpy.context.active_object; sun.name = "Sun"
    sun.data.energy = 3.5; sun.data.angle = 0.35
    sun.rotation_euler = (0.6, 0.2, 0.9)
if not bpy.data.objects.get("InteriorFill"):
    bpy.ops.object.light_add(type='AREA', location=(-3, -2, 2.6))
    fill = bpy.context.active_object; fill.name = "InteriorFill"
    fill.data.energy = 120; fill.data.size = 4
    fill.data.color = (1.0, 0.92, 0.8)
if not bpy.data.objects.get("ArchCamera"):
    bpy.ops.object.camera_add(location=(7, -9, 2.2))
    cam = bpy.context.active_object; cam.name = "ArchCamera"
    cam.data.lens = 35  # wide, architectural
    look_at(cam, (0, 0, 1.0))
    bpy.context.scene.camera = cam
try:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
except TypeError:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
bpy.context.scene.view_settings.look = 'AgX - Medium High Contrast'
print("Preset 'archviz' applied.")
''',
    },

    "dramatic": {
        "label": "Dramatic dark scene (rim light, low world)",
        "code": r'''
import bpy
from mathutils import Vector
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.02, 0.02, 0.04, 1)
bg.inputs["Strength"].default_value = 0.15

def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

if not bpy.data.objects.get("KeySpot"):
    bpy.ops.object.light_add(type='SPOT', location=(-3, -3, 6))
    key = bpy.context.active_object; key.name = "KeySpot"
    key.data.energy = 1200; key.data.spot_size = 0.8
    key.data.color = (1.0, 0.95, 0.85)
    look_at(key, (0, 0, 1))
if not bpy.data.objects.get("BlueRim"):
    bpy.ops.object.light_add(type='AREA', location=(4, 3, 2.5))
    rim = bpy.context.active_object; rim.name = "BlueRim"
    rim.data.energy = 700; rim.data.size = 3
    rim.data.color = (0.3, 0.5, 1.0)
    look_at(rim, (0, 0, 1))
if not bpy.data.objects.get("DramaticCamera"):
    bpy.ops.object.camera_add(location=(4, -6, 2.5))
    cam = bpy.context.active_object; cam.name = "DramaticCamera"
    cam.data.lens = 60
    look_at(cam, (0, 0, 1))
    bpy.context.scene.camera = cam
try:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
except TypeError:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
print("Preset 'dramatic' applied.")
''',
    },

    "outdoor": {
        "label": "Outdoor daylight (blue sky world, warm sun)",
        "code": r'''
import bpy
from mathutils import Vector
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.45, 0.65, 0.95, 1)
bg.inputs["Strength"].default_value = 1.0

def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

if not bpy.data.objects.get("Ground"):
    bpy.ops.mesh.primitive_plane_add(size=60)
    ground = bpy.context.active_object; ground.name = "Ground"
    gmat = bpy.data.materials.new("Grass")
    gmat.use_nodes = True
    gmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.38, 0.12, 1)
    gmat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.95
    ground.data.materials.append(gmat)
if not bpy.data.objects.get("Sun"):
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    sun = bpy.context.active_object; sun.name = "Sun"
    sun.data.energy = 4.0; sun.data.color = (1.0, 0.95, 0.85)
    sun.rotation_euler = (0.7, 0.2, 0.7)
if not bpy.data.objects.get("OutdoorCamera"):
    bpy.ops.object.camera_add(location=(9, -9, 5))
    cam = bpy.context.active_object; cam.name = "OutdoorCamera"
    cam.data.lens = 35
    look_at(cam, (0, 0, 1))
    bpy.context.scene.camera = cam
try:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
except TypeError:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
print("Preset 'outdoor' applied.")
''',
    },

    "clay": {
        "label": "Clay/blueprint render (single matte material, AO)",
        "code": r'''
import bpy
from mathutils import Vector
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.7, 0.75, 0.8, 1)
bg.inputs["Strength"].default_value = 1.2

def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

if not bpy.data.objects.get("ClaySun"):
    bpy.ops.object.light_add(type='SUN', location=(4, -4, 8))
    sun = bpy.context.active_object; sun.name = "ClaySun"
    sun.data.energy = 3.0
if not bpy.data.objects.get("ClayCamera"):
    bpy.ops.object.camera_add(location=(6, -6, 4))
    cam = bpy.context.active_object; cam.name = "ClayCamera"
    cam.data.lens = 50
    look_at(cam, (0, 0, 1))
    bpy.context.scene.camera = cam
try:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
except TypeError:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
print("Preset 'clay' applied (assign a single clay material to meshes if wanted).")
''',
    },
}


def list_presets():
    return {name: meta["label"] for name, meta in PRESETS.items()}


def preset_code(name):
    if name not in PRESETS:
        raise KeyError("unknown preset %r; choose from %s"
                       % (name, ", ".join(sorted(PRESETS))))
    return PRESETS[name]["code"]
