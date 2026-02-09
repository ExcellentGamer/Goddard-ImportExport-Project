import bpy
import sys
import re
import ast
import os
from .dynlist_utils import tokenize_list

# the file path to the sm64 source repo
sm64_source_dir = ""

# the vertex count of the default mario head
DEFAULT_VERTEX_COUNT = 644

# default params of the static display list in renderer.c
DEFAULT_MAX_GFX_IN_DL = 1900
DEFAULT_MAX_VERTS_IN_DL = 4000

# replacement code for goddard memory management
GD_MALLOC_SUB = """
    /*C MEM*/
    size = ALIGN(size, 8);
    sAllocMemory += size;
    return malloc(size);
    /*C MEM*/
"""
GD_FREE_SUB = """
    /*C MEM*/
    sAllocMemory -= sizeof(ptr);
    free(ptr);
    return;
    /*C MEM*/
"""

curr_context = None
total_vertex_count = 0
max_vertex_count_in_mesh = 0

def load_dynlist(filepath):
    text = ""
    with open(os.path.join(sm64_source_dir, filepath)) as file:
        text = file.read()
    return text

def modify_dynlist(dynlist, object, vert_data_name, face_data_name, list_data_name):
    global max_vertex_count_in_mesh, total_vertex_count
    
    # Clean up artifacts from previous broken exports.
    # - Some regex backreferences were previously emitted literally (e.g. "\\1[28]\\2").
    # - Some replacements accidentally inserted ASCII control characters (e.g. \x03) into EndGroup(...).
    dynlist = dynlist.replace("\x03", "")
    # Remove either "\1[NN]\2" or "\\1[NN]\\2" lines.
    dynlist = re.sub(r"^[\\]1\[\d+\][\\]2\s*$\r?\n?", "", dynlist, flags=re.M)
    dynlist = re.sub(r"^\\\\1\[\d+\]\\\\2\s*$\r?\n?", "", dynlist, flags=re.M)
    # Also remove if it appears without being on its own line.
    dynlist = re.sub(r"[\\]1\[\d+\][\\]2\s*\r?\n", "", dynlist)
    dynlist = re.sub(r"\\\\1\[\d+\]\\\\2\s*\r?\n", "", dynlist)
    
    # get a triangulated version of the object's mesh 
    tri_mod = object.modifiers.new("triangulate", "TRIANGULATE")
    depsgraph = curr_context.evaluated_depsgraph_get()
    eval_obj = object.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    object.modifiers.remove(tri_mod)

    vertex_data = []
    for vertex in mesh.vertices:
        vertex_data.append([
            int(vertex.co[0] * 212.77),
            int(vertex.co[1] * 212.77),
            int(vertex.co[2] * 212.77)
        ])
    max_vertex_count_in_mesh = max(max_vertex_count_in_mesh, len(mesh.vertices))
    total_vertex_count += len(mesh.vertices)
    vertex_data = str(vertex_data).replace("[", "{").replace("]", "}")

    face_data = []
    for face in mesh.polygons:
        face_data.append([
            face.material_index,
            face.vertices[0],
            face.vertices[1],
            face.vertices[2]
        ])
    face_data = str(face_data).replace("[", "{").replace("]", "}")

    # Insert vertex/face data into file.
    # sm64coopdx dynlists do not use VTX_NUM/FACE_NUM; they use static arrays with ARRAY_COUNT().
    if "#define VTX_NUM" in dynlist and "#define FACE_NUM" in dynlist:
        dynlist = re.sub(r"#define VTX_NUM (.*?)\n", "#define VTX_NUM " + str(len(mesh.vertices)) + " \n", dynlist, 1)
        dynlist = re.sub(
            vert_data_name+r"\[VTX_NUM\](.+?)};",
            vert_data_name+"[VTX_NUM][3] = " + vertex_data + ";",
            dynlist, 1, re.S
        )

        dynlist = re.sub(r"#define FACE_NUM (.*?)\n", "#define FACE_NUM " + str(len(mesh.polygons)) + " \n", dynlist, 1)
        dynlist = re.sub(
            face_data_name+r"\[FACE_NUM\](.+?)};",
            face_data_name+"[FACE_NUM][4] = " + face_data + ";",
            dynlist, 1, re.S
        )
    else:
        dynlist = re.sub(
            r"(static\s+s16\s+" + re.escape(vert_data_name) + r"\s*\[\]\[3\]\s*=\s*)\{.*?\};",
            lambda m: m.group(1) + vertex_data + ";",
            dynlist, 1, re.S,
        )
        dynlist = re.sub(
            r"(static\s+u16\s+" + re.escape(face_data_name) + r"\s*\[\]\[4\]\s*=\s*)\{.*?\};",
            lambda m: m.group(1) + face_data + ";",
            dynlist, 1, re.S,
        )
    
    # insert material data into file
    material_data = []
    for i, material_slot in enumerate(object.material_slots):
        material = material_slot.material
        material_data.append("MakeDynObj(D_MATERIAL, 0x0),")
        material_data.append("SetId("+str(i)+"),")
        
        color = material.diffuse_color
        color = (color[0], color[1], color[2])
        
        material_data.append("SetAmbient"+str(color)+",")
        material_data.append("SetDiffuse"+str(color)+",")

    list_length = 12 + len(material_data)

    # If a previous broken export replaced the dynlist declaration with a literal backreference
    # artifact (e.g. "\1[28]\2"), the sanitizer above will remove it. In that case, the list
    # can be left without a `struct DynList ... = {` declaration, and `BeginList()` ends up at
    # file scope, breaking compilation.
    if ("struct DynList " + list_data_name) not in dynlist:
        dynlist = re.sub(
            r"^([ \t]*)BeginList\(\),",
            lambda m: (
                "struct DynList " + list_data_name + "[" + str(list_length) + "] = {\n"
                + m.group(1) + "BeginList(),"
            ),
            dynlist, 1, re.M
        )

    dynlist = re.sub(
        r"(struct\s+DynList\s+" + re.escape(list_data_name) + r"\s*)\[\s*\d+\s*\](\s*=\s*\{)",
        lambda m: m.group(1) + "[" + str(list_length) + "]" + m.group(2),
        dynlist, 1
    )
    material_data = "\n".join(material_data)
    dynlist = re.sub(
        r"(^[ \t]*)StartGroup\(([^)]*?)\)\s*,?(.*?)(^[ \t]*)EndGroup\(([^)]*?)\)\s*,?",
        lambda m: (
            m.group(1) + "StartGroup(" + m.group(2) + "),\n"
            + ("" if not material_data else "\n".join(m.group(1) + "    " + line for line in material_data.split("\n")) + "\n")
            + m.group(1) + "EndGroup(" + ((m.group(5).strip()) if m.group(5).strip() else m.group(2)) + "),\n"
        ),
        dynlist, 1, re.S | re.M
    )

    try:
        eval_obj.to_mesh_clear()
    except Exception:
        pass

    return dynlist, list_length

def modify_master_dynlist(dynlist, objects):
    original_list = dynlist[:]
    
    token_list = tokenize_list(dynlist)
    
    weight_id_map = {
        0xD7: "eye.L", 0xCE: "eye.R",
        0xC5: "face?", 0xC2: "jaw",
        0xB9: "nose", 0xB0: "ear.L",
        0xA7: "ear.R", 0x9E: "cheek.L",
        0x95: "cheek.R", 0x8C: "upper_lip",
        0x83: "forehead", 0x6A: "root?",
        0x0F: "mustache.L", 0x06: "mustache.R",
        0x53: "eyebrow.L.L", 0x4A: "eyebrow.R.L",
        0x41: "eyebrow.L", 0x31: "eyebrow.R.R",
        0x28: "eyebrow.L.R", 0x1F: "eyebrow.R"
    }
    obj_id_map = {
        0xE1: "face", 0x3B: "eyebrow.L",
        0x5D: "eyebrow.R", 0x19: "mustache",

        "DYNOBJ_MARIO_FACE_SHAPE": "face",
        "DYNOBJ_MARIO_LEFT_EYEBROW_SHAPE": "eyebrow.L",
        "DYNOBJ_MARIO_RIGHT_EYEBROW_SHAPE": "eyebrow.R",
        "DYNOBJ_MARIO_MUSTACHE_SHAPE": "mustache",
    }
    
    i = 0
    current_object = None
    object_weights = {}
    current_vert_group = None
    weight_begin, weight_end = -1, -1
    had_any_weight_replacement = False
    while i < len(token_list):
        command, params = token_list[i]
        
        if command != "SetSkinWeight" and weight_begin != -1:
            existing_weight_block = token_list[weight_begin:weight_end]

            sublist = []
            if current_object is not None and current_vert_group is not None:
                print(current_object.name, len(current_object.data.vertices))
                vert_group_index = current_vert_group.index

                for j, vert in enumerate(current_object.data.vertices):
                    for grp in vert.groups:
                        if grp.group == vert_group_index and grp.weight != 0.0:
                            sublist.append(["SetSkinWeight", (j, grp.weight * 100.0)])

            # Only replace weights if we actually generated new ones.
            # If vertex groups are missing/mismatched for a custom head, preserving original
            # weights keeps cursor-driven deformation functioning.
            if len(sublist) > 0:
                del token_list[weight_begin:weight_end]
                token_list[weight_begin:weight_begin] = sublist
                had_any_weight_replacement = True
                i = weight_begin + len(sublist) + 1
            else:
                i = weight_end + 1

            weight_begin = -1
            weight_end = -1
            continue

        if command == "SetSkinShape":
            if current_object:
                bpy.ops.object.select_all(action="DESELECT")
                current_object.select_set(True)
                curr_context.view_layer.objects.active = current_object
                bpy.ops.object.delete()

            # use a version of the mesh with its modifiers applied
            bpy.ops.object.select_all(action="DESELECT")
            shape_key = params[0] if isinstance(params, tuple) else params
            shape_name = obj_id_map.get(shape_key)
            if shape_name is None or shape_name not in objects:
                i += 1
                continue
            objects[shape_name].select_set(True)
            curr_context.view_layer.objects.active = objects[shape_name]
            bpy.ops.object.duplicate()
            bpy.ops.object.modifier_add(type="TRIANGULATE")
            current_object = curr_context.view_layer.objects.active
            for mod in current_object.modifiers:
                try:
                    if isinstance(mod, bpy.types.ArmatureModifier):
                        bpy.ops.object.modifier_remove(modifier=mod.name)
                    else:
                        bpy.ops.object.modifier_apply(modifier=mod.name)
                except RuntimeError:
                    bpy.ops.object.modifier_remove(modifier=mod.name)
            
            for vert_group in current_object.vertex_groups:
                object_weights[vert_group.name] = vert_group
        elif command == "AttachNetToJoint":
            if params[1] in weight_id_map:
                current_vert_group = object_weights[weight_id_map[params[1]]]
            else:
                current_vert_group = None
        if command == "SetSkinWeight":
            if weight_begin == -1:
                weight_begin = i
                weight_end = i + 1
            else:
                weight_end = i + 1
        i+=1
    
    if current_object:
        bpy.ops.object.select_all(action="DESELECT")
        current_object.select_set(True)
        curr_context.view_layer.objects.active = current_object
        bpy.ops.object.delete()
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    
    list_string = "dynlist_mario_master["+str(len(token_list))+"] = {\n"
    indent = "    "
    for command, params in token_list:
        if command in ["EndGroup", "EndNetSubGroup"]:
            indent = indent[:-4]
        
        param_string = str(params).replace("'", "")
        if not type(params) is tuple:
            param_string = "(" + param_string + ")"
        list_string += indent + command + param_string + ",\n"

        if command in ["StartGroup", "MakeNetWithSubGroup"]:
            indent += "    "
    list_string += "};"
    
    list_string = re.sub(r"dynlist_mario_master\[(.+)};", list_string, original_list, 1, re.S)
    
    return list_string, len(token_list)

def split_dynlists(dynlist):
    lists = []

    splitpoint = "#define VTX_NUM"
    indices = []
    start = 0
    while True:
        idx = dynlist.find(splitpoint, start)
        if idx == -1:
            break
        indices.append(idx)
        start = idx + len(splitpoint)

    if len(indices) <= 1:
        return [dynlist]

    for i, idx in enumerate(indices):
        if i + 1 < len(indices):
            lists.append(dynlist[idx:indices[i + 1]])
        else:
            lists.append(dynlist[idx:])

    if indices[0] != 0:
        lists[0] = dynlist[:indices[0]] + lists[0]

    return lists

def exceute(op, context):
    global curr_context, sm64_source_dir, total_vertex_count, max_vertex_count_in_mesh
    
    total_vertex_count = 0
    max_vertex_count_in_mesh = 0
    curr_context = context
    goddard_head = context.active_object

    if not goddard_head:
        op.report({'ERROR'}, "A goddard head is not selected!")
        return {'CANCELLED'}

    # Get goddard meshes
    goddard_children = goddard_head.children
    goddard_meshes = {}
    mesh_names = ["eye.L", "eye.R", "eyebrow.L", "eyebrow.R", "face", "mustache"]
    for mesh in goddard_children:
        if "eye.L" in mesh.name:
            goddard_meshes["eye.L"] = mesh
        elif "eye.R" in mesh.name:
            goddard_meshes["eye.R"] = mesh
        elif "eyebrow.L" in mesh.name:
            goddard_meshes["eyebrow.L"] = mesh
        elif "eyebrow.R" in mesh.name:
            goddard_meshes["eyebrow.R"] = mesh
        elif "face" in mesh.name:
            goddard_meshes["face"] = mesh
        elif "mustache" in mesh.name:
            goddard_meshes["mustache"] = mesh

    if len(goddard_meshes.items()) != 6:
        missing_meshes = [name for name in mesh_names if not name in goddard_meshes.keys()]
        op.report({'ERROR'}, "The selected object does not have the following mesh children: %s" %\
            str(missing_meshes)
        )
        return {'CANCELLED'}

    sm64_source_dir = bpy.path.abspath(context.scene.goddard.source_dir)
    dynlist_files = {
        "eyes": "src/goddard/dynlists/dynlists_mario_eyes.c",
        "eyebrows_mustache": "src/goddard/dynlists/dynlists_mario_eyebrows_mustache.c",
        "face": "src/goddard/dynlists/dynlist_mario_face.c",
        "master": "src/goddard/dynlists/dynlist_mario_master.c"
    }

    if not os.path.exists(sm64_source_dir):
        op.report({'ERROR'}, "The source directory does not exist!")
        return {'CANCELLED'}

    # load and modify the master dynlist file
    master_dynlist = load_dynlist(dynlist_files["master"])
    master_dynlist, master_size = modify_master_dynlist(master_dynlist, goddard_meshes)

    # load and modify the dynlist file that the face will be saved in.
    face_dynlist = load_dynlist(dynlist_files["face"])
    face_dynlist, face_size = modify_dynlist(face_dynlist, goddard_meshes["face"], "mario_Face_VtxData", "mario_Face_FaceData", "dynlist_mario_face_shape")

    # load and modify the dynlist file that the eyes will be saved in.
    eyes_dynlists = load_dynlist(dynlist_files["eyes"])
    eyes_dynlists, eye_size_r = modify_dynlist(eyes_dynlists, goddard_meshes["eye.R"], "verts_mario_eye_right", "facedata_mario_eye_right", "dynlist_mario_eye_right_shape")
    eyes_dynlists, eye_size_l = modify_dynlist(eyes_dynlists, goddard_meshes["eye.L"], "verts_mario_eye_left", "facedata_mario_eye_left", "dynlist_mario_eye_left_shape")

    # load and modify the dynlist file that the eyebrows and mustache will be saved in.
    brow_stache_dynlists = load_dynlist(dynlist_files["eyebrows_mustache"])
    brow_stache_dynlists, eyebrow_size_r = modify_dynlist(brow_stache_dynlists, goddard_meshes["eyebrow.R"], "verts_mario_eyebrow_right", "facedata_mario_eyebrow_right", "dynlist_mario_eyebrow_right_shape")
    brow_stache_dynlists, eyebrow_size_l = modify_dynlist(brow_stache_dynlists, goddard_meshes["eyebrow.L"], "verts_mario_eyebrow_left", "facedata_mario_eyebrow_left", "dynlist_mario_eyebrow_left_shape")
    brow_stache_dynlists, mustache_size = modify_dynlist(brow_stache_dynlists, goddard_meshes["mustache"], "verts_mario_mustache", "facedata_mario_mustache", "dynlist_mario_mustache_shape")

    os.makedirs(sm64_source_dir + "/src/goddard/dynlists/", exist_ok=True)

    # write the dynlist lengths into the dynlists header file.
    with open(sm64_source_dir+"/src/goddard/dynlists/dynlists.h", "r") as src_head_file:
        header = src_head_file.read()
        header = re.sub(r"(dynlist_mario_master)\[(.+?)\]", r"\1["+str(master_size)+"]", header)
        header = re.sub(r"(dynlist_mario_face)\[(.+?)\]", r"\1["+str(face_size)+"]", header)
        header = re.sub(r"(dynlist_mario_eye_right)\[(.+?)\]", r"\1["+str(eye_size_r)+"]", header)
        header = re.sub(r"(dynlist_mario_eye_left)\[(.+?)\]", r"\1["+str(eye_size_l)+"]", header)
        header = re.sub(r"(dynlist_mario_eyebrow_right)\[(.+?)\]", r"\1["+str(eyebrow_size_r)+"]", header)
        header = re.sub(r"(dynlist_mario_eyebrow_left)\[(.+?)\]", r"\1["+str(eyebrow_size_l)+"]", header)
        header = re.sub(r"(dynlist_mario_mustache)\[(.+?)\]", r"\1["+str(mustache_size)+"]", header)

        with open(sm64_source_dir+"/src/goddard/dynlists/dynlists.h", "w") as dest_head_file:
            dest_head_file.write(header)

    # write the dynlists into their respective files.
    with open(sm64_source_dir+"/src/goddard/dynlists/dynlist_mario_master.c", 'w') as file:
        if not "BLENDER" in face_dynlist:
            file.write("// MODIFIED BY A BLENDER ADDON //\n")
        file.write(master_dynlist)

    with open(sm64_source_dir+"/src/goddard/dynlists/dynlist_mario_face.c", "w") as file:
        if not "BLENDER" in face_dynlist:
            file.write("// MODIFIED BY A BLENDER ADDON //\n")
        file.write(face_dynlist)

    with open(sm64_source_dir+"/src/goddard/dynlists/dynlists_mario_eyes.c", "w") as file:
        if not "BLENDER" in eyes_dynlists:
            file.write("// MODIFIED BY A BLENDER ADDON //\n")
        file.write(eyes_dynlists)

    with open(sm64_source_dir+"/src/goddard/dynlists/dynlists_mario_eyebrows_mustache.c", "w") as file:
        if not "BLENDER" in brow_stache_dynlists:
            file.write("// MODIFIED BY A BLENDER ADDON //\n")
        file.write(brow_stache_dynlists)
    
    # prepend the gd_malloc and gd_free functions with stdlib malloc and free respectively.
    with open(sm64_source_dir + "/src/goddard/renderer.c", 'r') as src_file:
        code = src_file.read()
        
        if context.scene.goddard.c_memory_management:
            if code.find("<stdlib.h>") == -1:
                code = "#include <stdlib.h>\n" + code
            if code.find(GD_MALLOC_SUB) == -1:
                code = re.sub(r"(\*gd_malloc\((.*?){)",r"\1" + GD_MALLOC_SUB, code, 1, re.S)
            if code.find(GD_FREE_SUB) == -1:
                code = re.sub(r"(gd_free\((.*?){)",r"\1" + GD_FREE_SUB, code, 1, re.S)
        else:
            code = code.replace("#include <stdlib.h>\n", "")
            code = code.replace(GD_MALLOC_SUB, "")
            code = code.replace(GD_FREE_SUB, "")

        ratio = total_vertex_count / DEFAULT_VERTEX_COUNT
        code = re.sub(r"(sStaticDl = new_gd_dl\(0,)(.*?),(.*?),",
            r"\1 %d, %d," % (DEFAULT_MAX_GFX_IN_DL * ratio, DEFAULT_MAX_VERTS_IN_DL * ratio),
            code, 1, re.S
        )
    
        with open(sm64_source_dir + "/src/goddard/renderer.c", 'w') as dst_file:
            dst_file.write(code)

    # adjust maximum vertex count in dynlist_proc.c
    with open(sm64_source_dir + "/src/goddard/dynlist_proc.c", 'r') as src_file:
        code = src_file.read()
        code = re.sub(r"(#define VTX_BUF_SIZE)(.*?)\n", r"\1 %d\n" % (max(max_vertex_count_in_mesh * 1.5, 3000.0)), code, 1, re.S)

        with open(sm64_source_dir + "/src/goddard/dynlist_proc.c", 'w') as dst_file:
            dst_file.write(code)

    return {'FINISHED'}
