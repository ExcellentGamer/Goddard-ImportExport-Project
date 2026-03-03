
import bpy
import ast
import os
import sys
import re
import math
import time
from mathutils import Matrix, Vector, Euler
from .dynlist_utils import tokenize_list
from .dynlist_lookup import DynObjLUT

D_MATERIAL = bpy.types.Material
D_LIGHT = bpy.types.Light

id_database = {}

current_mat = None
current_object = None

current_context = None
vertex_count = 0

def select_object(object):
    object.select_set(True)
    current_context.view_layer.objects.active = object

def MakeDynObj(type, meta):
    global current_mat
    global current_object

    if type == D_MATERIAL:
        current_mat = bpy.data.materials.new(name = "n64_mat")
    elif type == D_LIGHT:
        current_mat = None
        current_object = bpy.data.objects.new("n64_light", bpy.data.lights.new(name = "Light", type = "POINT"))
        current_context.collection.objects.link(current_object)
        select_object(current_object)

def SetId(id):
    global current_object
    global current_mat

    if current_mat:
        if len(current_object.data.materials) > id:
            current_object.data.materials[id] = current_mat
        else:
            current_object.data.materials.append(current_mat)
    else:
        id_database[id] = current_object

def SetShapePtrPtr(null_arg):
    pass

# only used for eyes
def SetAmbient(r, g, b):
    pass

def SetDiffuse(r, g, b):
    if current_mat:
        current_mat.diffuse_color = (r, g, b, 1.0)
    else:
        current_object.color = (r, g, b, 1.0)

def SetFlag(null_arg):
    pass


def load_dynlist(filepath, vertex_data, face_data):
    global vertex_count
    if not os.path.exists(filepath):
        return None

    obj = None
    with open(filepath) as file:
        text = file.read()
        
        # Load vertices
        vertex_list = []
        arr_start1 = text.find(vertex_data + " = ")
        if arr_start1 != -1:
            arr_start1 += len(vertex_data + " = ")
            arr_end1 = text.find("};", arr_start1) + 1
            v_l = text[arr_start1:arr_end1].replace("{", "[").replace("}", "]")
            vertex_list = ast.literal_eval(v_l)
            vertex_count += len(vertex_list)
            vertex_list = [val for sublist in vertex_list for val in sublist]
            for idx, _ in enumerate(vertex_list):
                vertex_list[idx] /= 212.77
        else:
            print("Couldn't find vertex data!")
            
        # Load faces and material indices
        face_list = []
        mat_id_list = []
        arr_start2 = text.find(face_data + " = ")
        if arr_start2 != -1:
            arr_start2 += len(face_data + " = ")
            arr_end2 = text.find("};", arr_start2) + 1
            face_list = ast.literal_eval(text[arr_start2:arr_end2].replace("{", "[").replace("}", "]"))
            temp_list = []
            for idx, face in enumerate(face_list):
                temp_list.append(face[1:4])
                mat_id_list.append(face[0])
            face_list = [val for sublist in temp_list for val in sublist]
        else:
            print("Couldn't find face data!")
        
        # Apply vertices
        mesh = bpy.data.meshes.new(name='Mario Head Mesh')
        mesh.vertices.add(len(vertex_list) // 3)
        mesh.vertices.foreach_set("co", vertex_list)
        
        # Apply Triangles
        mesh.loops.add(len(face_list))
        mesh.loops.foreach_set("vertex_index", face_list)
        mesh.polygons.add(len(face_list) // 3)
        mesh.polygons.foreach_set("loop_start", range(0, len(face_list), 3))
        mesh.polygons.foreach_set("loop_total", [3] * (len(face_list) // 3))
        mesh.polygons.foreach_set("material_index", mat_id_list)
        
        mesh.update()
        mesh.validate()
        
        # Create Object whose Object Data is our new mesh
        global current_object
        obj = bpy.data.objects.new('Mario Head', mesh)
        current_object = obj
        
        # Load Materials
        arr_start3 = text.find("MakeDynObj(D_MATERIAL", arr_start2)
        if arr_start3 != -1:
            arr_end3 = text.find("EndGroup", arr_start3) - 1
            dynlist = text[arr_start3:arr_end3].replace(",\n", "\n").replace(" ", "")

            tmp1 = dynlist.split("\n")
            tmp2 = [i for i in tmp1 if "//" not in i[0:2]]
            tmp3 = [i.split("//")[0] for i in tmp2]
            new_dynlist = "\n".join(tmp3)
            exec(new_dynlist)
        
        # Add Object to the scene
        current_context.collection.objects.link(obj)

        select_object(obj)
        bpy.ops.object.shade_smooth()
    
    return obj


def load_data_from_master_list(filepath, objects):
    with open(filepath) as file:
        text = file.read()
        
        dynlist = tokenize_list(text)
        
        mesh_weights = {}
        curr_armature = None
        curr_mesh = None
        curr_bone = None
        curr_bone_idx = 0
        curr_weights = []
        curr_object = None

        bone_armature_map = {}

        obj_id_map = {
            "face": "DYNOBJ_MARIO_FACE_SHAPE",
            "eyebrow.L": "DYNOBJ_MARIO_LEFT_EYEBROW_SHAPE",
            "eyebrow.R": "DYNOBJ_MARIO_RIGHT_EYEBROW_SHAPE",
            "mustache": "DYNOBJ_MARIO_MUSTACHE_SHAPE",
            # these are dynamically set by the game
            # "eye.L": "DYNOBJ_MARIO_LEFT_EYE_SHAPE",
            # "eye.R": "DYNOBJ_MARIO_RIGHT_EYE_SHAPE",
        }
        bone_id_map = {
            "DYNOBJ_RIGHT_EYELID_JOINT_1": "eyelid.L",
            "DYNOBJ_LEFT_EYELID_JOINT_1": "eyelid.R",
            "DYNOBJ_MARIO_RIGHT_JAW_JOINT": "jaw.R",
            "DYNOBJ_MARIO_LEFT_JAW_JOINT": "jaw.L",
            "DYNOBJ_MARIO_NOSE_JOINT_1": "nose.1",
            "DYNOBJ_MARIO_NOSE_JOINT_2": "nose.2",
            "DYNOBJ_MARIO_RIGHT_EAR_JOINT_1": "ear.R",
            "DYNOBJ_MARIO_LEFT_EAR_JOINT_1": "ear.L",
            "DYNOBJ_MARIO_RIGHT_LIP_CORNER_JOINT_1": "cheek.R",
            "DYNOBJ_MARIO_LEFT_LIP_CORNER_JOINT_1": "cheek.L",
            "DYNOBJ_MARIO_UNKNOWN_140": "upper_lip",
            "DYNOBJ_MARIO_CAP_JOINT_1": "forehead",
            "DYNOBJ_MARIO_LEFT_EYE_JOINT_1": "eye.L",
            "DYNOBJ_MARIO_RIGHT_EYE_JOINT_1": "eye.R",
            "DYNOBJ_MARIO_LEFT_MUSTACHE_JOINT_1": "mustache.L",
            "DYNOBJ_MARIO_RIGHT_MUSTACHE_JOINT_1": "mustache.R",
            "DYNOBJ_MARIO_RIGHT_EYEBROW_RPART_JOINT_1": "eyebrow.L.L",
            "DYNOBJ_MARIO_RIGHT_EYEBROW_LPART_JOINT_1": "eyebrow.R.L",
            "DYNOBJ_MARIO_RIGHT_EYEBROW_MPART_JOINT_1": "eyebrow.L",
            "DYNOBJ_MARIO_LEFT_EYEBROW_LPART_JOINT_1": "eyebrow.R.R",
            "DYNOBJ_MARIO_LEFT_EYEBROW_RPART_JOINT_1": "eyebrow.L.R",
            "DYNOBJ_MARIO_LEFT_EYEBROW_MPART_JOINT_1": "eyebrow.R",
        }

        def remove_empty_weights():
            pass
            # nonlocal curr_bone_idx
            # if len(curr_weights) == 0 and curr_bone_idx != 0:
            #     mesh_weights[curr_mesh].pop(curr_bone_idx)
            #     curr_bone_idx = 0
        
        def set_shape_pointer(armature, shape_obj):
            for mod in shape_obj.modifiers:
                if isinstance(mod, bpy.types.ArmatureModifier) and mod.object == armature:
                    return

            bpy.ops.object.select_all(action='DESELECT')
            select_object(shape_obj)

            bpy.ops.object.modifier_add(type='ARMATURE')
            shape_obj.modifiers[-1].show_expanded = False
            shape_obj.modifiers[-1].object = armature

        for command, params in dynlist:
            print(command,params)
            if (command == "MakeDynObj" and "D_NET" in params):
                curr_object = bpy.data.objects.new(params[1], bpy.data.armatures.new("n64_net"))
                current_context.collection.objects.link(curr_object)
                select_object(curr_object)
                curr_object.show_in_front = True
                # objects[hex(DynObjLUT[params[1]])] = curr_object
                curr_armature = curr_object
                objects[params[1]] = curr_object

            elif (command == "MakeNetWithSubGroup"):
                if type(params) is int:
                    curr_object = bpy.data.objects.new(hex(params), bpy.data.armatures.new("n64_net"))
                else:
                    curr_object = bpy.data.objects.new(params, bpy.data.armatures.new("n64_net"))
                current_context.collection.objects.link(curr_object)
                select_object(curr_object)
                curr_object.show_in_front = True
                # objects[hex(DynObjLUT[params[1]])] = curr_object
                curr_armature = curr_object
                if type(params) is int:
                    objects[hex(params)] = curr_object
                else:
                    objects[params] = curr_object
            
            elif command == "SetScale":
                if isinstance(curr_object, bpy.types.Object):
                    curr_object.scale = params

            elif command == "SetAttachOffset":
                offset = [num / 212.77 for num in params]
                if isinstance(curr_object, bpy.types.Object):
                    curr_object.location = offset
                elif isinstance(curr_object, bpy.types.EditBone):
                    curr_object.matrix = Matrix.Translation(offset) @ curr_object.matrix
            
            elif command == "SetRotation":
                if isinstance(curr_object, bpy.types.Object):
                    curr_object.rotation_euler = params
                elif isinstance(curr_object, bpy.types.EditBone):
                    print("Step 0",curr_object)
                    print("Step 1",curr_object.matrix)
                    print("Step 2",[math.radians(rot) for rot in params])
                    print("Step 3",Euler([math.radians(rot) for rot in params]))
                    print("Step 4",Euler([math.radians(rot) for rot in params]).to_matrix())
                    print("Step 5",Euler([math.radians(rot) for rot in params]).to_matrix().to_4x4())
                    print("Step FINAL",Euler([math.radians(rot) for rot in params]).to_matrix().to_4x4())
                    curr_object.matrix = Euler([math.radians(rot) for rot in params]).to_matrix().to_4x4() @ curr_object.matrix
            
            elif command == "SetSkinShape":
                # remove_empty_weights()
                # mesh_weights.setdefault(params, {})

                curr_mesh = params

                obj_name = [k for k, v in obj_id_map.items() if v == params]
                if len(obj_name) == 0:
                    continue
                set_shape_pointer(curr_armature, objects[obj_name[0]])
            
            elif command == "AttachTo":
                if params[1] == "DYNOBJ_MARIO_MAIN_ANIMATOR":
                    continue

                bpy.ops.object.select_all(action='DESELECT')
                if isinstance(curr_object, bpy.types.EditBone):
                    armature = bone_armature_map[curr_object]
                    select_object(armature)
                    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                    curr_object.select = True
                    armature.data.edit_bones.active = curr_object
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                else:
                    select_object(curr_object)
                
                other_obj = objects[params[1]]
                
                print("Attach %s to %s" % (curr_object, other_obj))
                
                if isinstance(other_obj, bpy.types.EditBone):
                    armature = bone_armature_map[other_obj]
                    select_object(armature)
                    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                    other_obj.select = True
                    armature.data.edit_bones.active = other_obj
                    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                    bpy.ops.object.parent_set(type='BONE')
                else:
                    select_object(other_obj)
                    bpy.ops.object.parent_set()
    
            elif command == "MakeAttachedJoint":
                # Save previous joint's weights before starting new joint
                if curr_bone_idx and curr_mesh and len(curr_weights) > 0:
                    if curr_mesh not in mesh_weights:
                        mesh_weights[curr_mesh] = {}
                    mesh_weights[curr_mesh][curr_bone_idx] = curr_weights
                
                curr_weights = []

                select_object(curr_armature)
                bpy.ops.object.mode_set(mode='EDIT', toggle=False)
                curr_bone_idx = params
                curr_bone = curr_armature.data.edit_bones.new("bone")

                if params in bone_id_map.keys():
                    bone_name = bone_id_map[params]
                elif isinstance(params, int):
                    bone_name = f"joint_0x{params:02X}"
                elif isinstance(params, str):
                    bone_name = params
                else:
                    bone_name = repr(params)
                
                curr_bone.name = bone_name

                # curr_bone.name = "TESTBONE"+str(hash(time.time()))

                curr_bone.head = (0.0, 0.0, 0.0)
                curr_bone.tail = (0.0, 0.5, 0.0)
                curr_bone.matrix = Matrix.Identity(4)
                bpy.ops.object.mode_set(mode='OBJECT')


                print("Attach Net %s to Joint %s" % (curr_armature.name, bone_name))

                objects[params] = curr_bone
                bone_armature_map[curr_bone] = curr_armature
            elif command == "SetSkinWeight":
                curr_weights.append((params[0], params[1] / 100.0))
        
        # Save last joint's weights
        if curr_bone_idx and curr_mesh and len(curr_weights) > 0:
            if curr_mesh not in mesh_weights:
                mesh_weights[curr_mesh] = {}
            mesh_weights[curr_mesh][curr_bone_idx] = curr_weights
        
        # Apply collected weights to mesh vertex groups
        for obj_name, mesh_id in obj_id_map.items():
            if mesh_id not in mesh_weights:
                continue
            if obj_name not in objects:
                continue
            
            mesh_obj = objects[obj_name]
            for joint_id, weights in mesh_weights[mesh_id].items():
                # Get the bone name for this joint
                if joint_id in bone_id_map:
                    vg_name = bone_id_map[joint_id]
                elif isinstance(joint_id, int):
                    vg_name = f"joint_0x{joint_id:02X}"
                else:
                    vg_name = str(joint_id)
                
                # Create vertex group and add weights
                vert_group = mesh_obj.vertex_groups.new(name=vg_name)
                for index, weight in weights:
                    vert_group.add([index], weight, "REPLACE")


def execute(op, context):
    global current_context, vertex_count

    source_dir = bpy.path.abspath(context.scene.goddard.source_dir)
    goddard_file_path = os.path.join(source_dir, "src/goddard/dynlists")
    bpy.ops.object.select_all(action='DESELECT')
    current_context = context
    vertex_count = 0

    if not os.path.exists(source_dir):
        op.report({'ERROR'}, "The source directory does not exist!")
        return {'CANCELLED'}
    
    mario_objects = {
        "face": load_dynlist(
            os.path.join(goddard_file_path, "dynlist_mario_face.c"),
            "mario_Face_VtxData[][3]",
            "mario_Face_FaceData[][4]"
        ),
        "eyebrow.L": load_dynlist(
            os.path.join(goddard_file_path, "dynlists_mario_eyebrows_mustache.c"),
            "verts_mario_eyebrow_left[][3]",
            "facedata_mario_eyebrow_left[][4]"
        ),
        "eyebrow.R": load_dynlist(
            os.path.join(goddard_file_path, "dynlists_mario_eyebrows_mustache.c"),
            "verts_mario_eyebrow_right[][3]",
            "facedata_mario_eyebrow_right[][4]"
        ),
        "mustache": load_dynlist(
            os.path.join(goddard_file_path, "dynlists_mario_eyebrows_mustache.c"),
            "verts_mario_mustache[][3]",
            "facedata_mario_mustache[][4]"
        ),
        "eye.L": load_dynlist(
            os.path.join(goddard_file_path, "dynlists_mario_eyes.c"),
            "verts_mario_eye_left[][3]",
            "facedata_mario_eye_left[][4]"
        ),
        "eye.R": load_dynlist(
            os.path.join(goddard_file_path, "dynlists_mario_eyes.c"),
            "verts_mario_eye_right[][3]",
            "facedata_mario_eye_right[][4]"
        )
    }

    if None in mario_objects.items():
        op.report({'ERROR'}, "Dynlists could not be loaded!")
        return {'CANCELLED'}

    load_data_from_master_list(os.path.join(goddard_file_path, "dynlist_mario_master.c"), mario_objects)

    bpy.ops.object.select_all(action='DESELECT')
    for name, obj in mario_objects.items():
        if not isinstance(obj, bpy.types.Object):
            continue
        obj.name = hex(name) if isinstance(name, int) else str(name)

        if obj.parent == None:
            select_object(obj)

    # Mario's eye positions are generated by the game, so the following acts as a hardcoded placeholder.
    mario_objects["eye.L"].location = (0.31642, 0.737687, 0.032769)
    mario_objects["eye.L"].rotation_euler = (math.radians(45.3), math.radians(-85), math.radians(34.2))
    mario_objects["eye.R"].location = (-0.186127, 0.736151, 0.019117)
    mario_objects["eye.R"].rotation_euler = (math.radians(110), math.radians(-79.4), math.radians(161))

    head = bpy.data.objects.new("Mario Head", None)
    head.empty_display_type = "SPHERE"
    head.empty_display_size = 2.2
    context.collection.objects.link(head)
    select_object(head)
    bpy.ops.object.parent_set()
    head.rotation_euler = (math.radians(90.0), 0, 0)

    print(vertex_count)

    return {'FINISHED'}

