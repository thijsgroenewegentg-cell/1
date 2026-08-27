# SPDX-License-Identifier: MIT
"""
Reusable Blender Python toolkit, injected into the agent's exec environment.

For our own bridge transport this code is exec'd once into the persistent
namespace (so helpers are available as plain functions). For the BlenderMCP
addon - which uses a FRESH namespace per execute_code call - the same source
is prepended to every code block. Everything is self-contained, bpy-only.
"""

HELPERS_SOURCE = r'''
from mathutils import Vector


def clear_scene():
    """Remove every object and orphaned datablock."""
    import bpy
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                  bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            block.remove(item)


def make_material(name, color, roughness=0.5, metallic=0.0,
                  emission=None, emission_strength=1.0,
                  transmission=0.0, alpha=1.0):
    """Create a Principled-BSDF material. color/alpha are 0-1 RGBA-ish."""
    import bpy
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    r, g, b = color[0], color[1], color[2]
    bsdf.inputs["Base Color"].default_value = (r, g, b, alpha)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = transmission
    if emission is not None:
        er, eg, eb = emission
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (er, eg, eb, 1)
            bsdf.inputs["Emission Strength"].default_value = emission_strength
        elif "Emission" in bsdf.inputs:
            bsdf.inputs["Emission"].default_value = (er, eg, eb, 1)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emission_strength
    if alpha < 1.0:
        try:
            mat.blend_method = 'BLEND'
        except Exception:
            pass
    return mat


def assign_material(obj, mat):
    if hasattr(obj.data, "materials"):
        obj.data.materials.append(mat)


def add_primitive(kind, name=None, location=(0, 0, 0), rotation=(0, 0, 0),
                  scale=(1, 1, 1), material=None, **kw):
    """Add a mesh primitive. kind: cube, sphere, cylinder, cone, plane, torus, circle."""
    import bpy
    ops = {
        "cube": "primitive_cube_add",
        "sphere": "primitive_uv_sphere_add",
        "uv_sphere": "primitive_uv_sphere_add",
        "ico_sphere": "primitive_ico_sphere_add",
        "cylinder": "primitive_cylinder_add",
        "cone": "primitive_cone_add",
        "plane": "primitive_plane_add",
        "torus": "primitive_torus_add",
        "circle": "primitive_circle_add",
    }
    fn = getattr(bpy.ops.mesh, ops[kind])
    fn(location=location, rotation=rotation, **kw)
    obj = bpy.context.active_object
    if name:
        obj.name = name
    obj.scale = scale
    if material is not None:
        assign_material(obj, material)
    return obj


def point_at(obj, target, track='-Z', up='Y'):
    """Rotate an object (camera/light) to look at a world-space point."""
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat(track, up).to_euler()
    return obj


def add_camera(name="Camera", location=(7, -7, 5), target=(0, 0, 1), lens=50):
    import bpy
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.lens = lens
    point_at(cam, target)
    bpy.context.scene.camera = cam
    return cam


def add_light(kind='AREA', name=None, location=(0, 0, 5), energy=500,
              color=(1, 1, 1), target=None, size=5):
    """kind: SUN, AREA, POINT, SPOT."""
    import bpy
    bpy.ops.object.light_add(type=kind, location=location)
    light = bpy.context.active_object
    if name:
        light.name = name
    light.data.energy = energy
    light.data.color = color
    if hasattr(light.data, "size"):
        light.data.size = size
    if target is not None:
        point_at(light, target)
    return light


def set_world(color=(0.05, 0.05, 0.05), strength=0.3):
    import bpy
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (color[0], color[1], color[2], 1)
    bg.inputs["Strength"].default_value = strength


def use_eevee():
    """Set Eevee across Blender versions (4.2 renamed it)."""
    import bpy
    for engine in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            bpy.context.scene.render.engine = engine
            return engine
        except TypeError:
            continue
    return bpy.context.scene.render.engine


def use_cycles(samples=64):
    import bpy
    bpy.context.scene.render.engine = 'CYCLES'
    try:
        bpy.context.scene.cycles.samples = samples
    except Exception:
        pass


def set_render_resolution(x=1280, y=720, percentage=100):
    import bpy
    r = bpy.context.scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = x, y, percentage


def smooth_shading(obj):
    import bpy
    for poly in obj.data.polygons:
        poly.use_smooth = True


def add_bevel(obj, width=0.05, segments=3):
    mod = obj.modifiers.new("Bevel", 'BEVEL')
    mod.width = width
    mod.segments = segments
    return mod


def add_subsurf(obj, levels=2):
    mod = obj.modifiers.new("Subsurf", 'SUBSURF')
    mod.levels = levels
    return mod


def look_for(name_part, obj_type=None):
    """Find an object by case-insensitive name substring."""
    import bpy
    name_part = name_part.lower()
    for obj in bpy.data.objects:
        if name_part in obj.name.lower() and (obj_type is None or obj.type == obj_type):
            return obj
    return None


def ground_objects(names=None, margin=0.0):
    """Snap object origins' lowest bbox point to z=0 (or margin)."""
    import bpy
    objs = [bpy.data.objects[n] for n in names] if names else list(bpy.context.scene.objects)
    for obj in objs:
        if obj.type not in ('MESH', 'CURVE', 'FONT'):
            continue
        import mathutils
        xs, ys, zs = [], [], []
        for corner in obj.bound_box:
            w = obj.matrix_world @ mathutils.Vector(corner)
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
        obj.location.z += (margin - min(zs))


def animate_linear(obj, frame_start, frame_end, start_loc, end_loc):
    import bpy
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = frame_start, frame_end
    obj.location = start_loc
    obj.keyframe_insert("location", frame=frame_start)
    obj.location = end_loc
    obj.keyframe_insert("location", frame=frame_end)


def animate_rotation(obj, frame_start, frame_end, axis='Z', turns=1):
    import bpy
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = min(scene.frame_start, frame_start), max(scene.frame_end, frame_end)
    idx = {'X': 0, 'Y': 1, 'Z': 2}[axis]
    obj.rotation_euler[idx] = 0
    obj.keyframe_insert("rotation_euler", frame=frame_start)
    obj.rotation_euler[idx] = 6.2831853 * turns
    obj.keyframe_insert("rotation_euler", frame=frame_end)


def frame_all(camera_target=(0, 0, 1)):
    """A safe default 3/4 camera + key/fill/rim lighting if none exist."""
    import bpy
    if bpy.context.scene.camera is None:
        add_camera(location=(7, -7, 5), target=camera_target)
    if not [o for o in bpy.data.objects if o.type == 'LIGHT']:
        add_light('AREA', "KeyLight", location=(5, -5, 6), energy=600, target=camera_target)
        add_light('AREA', "FillLight", location=(-5, -2, 3), energy=200,
                  color=(0.8, 0.85, 1.0), target=camera_target)
        add_light('SUN', "SunRim", location=(0, 6, 8), energy=2.0)


def quick_setup(engine='eevee', world_strength=0.35, resolution=(1280, 720)):
    """One-call: engine, world, camera, 3-point light. Good baseline."""
    use_eevee() if engine == 'eevee' else use_cycles()
    set_world((0.05, 0.07, 0.10), world_strength)
    set_render_resolution(*resolution)
    frame_all()
'''

# Helper names, surfaced in the system prompt so the model uses them.
HELPER_NAMES = [
    "clear_scene", "make_material", "assign_material", "add_primitive",
    "point_at", "add_camera", "add_light", "set_world", "use_eevee",
    "use_cycles", "set_render_resolution", "smooth_shading", "add_bevel",
    "add_subsurf", "look_for", "ground_objects", "animate_linear",
    "animate_rotation", "frame_all", "quick_setup",
]
