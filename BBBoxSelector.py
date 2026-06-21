# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, generators, print_function, unicode_literals
import sys

import maya.cmds as cmds
from maya.common.ui import LayoutManager
import maya.api.OpenMaya as om

sys.dont_write_bytecode = True

def _get_dag_path(node_name):
    sel = om.MSelectionList()
    sel.add(node_name)
    return sel.getDagPath(0)


def _get_mesh_shape_path(node_name):
    """
    transform / shape どちらが来ても mesh shape の MDagPath を返す
    """
    dag = _get_dag_path(node_name)

    if dag.node().hasFn(om.MFn.kTransform):
        dag.extendToShape()

    if not dag.node().hasFn(om.MFn.kMesh):
        raise RuntimeError("メッシュ shape が見つからないよ: {}".format(node_name))

    return dag


def _set_active_component_selection(mesh_dag, component_obj):
    """
    APIコンポーネント選択をアクティブ選択に反映
    """
    sel = om.MSelectionList()
    sel.add((mesh_dag, component_obj))
    om.MGlobal.setActiveSelectionList(sel)


def _create_single_index_component(component_type, indices):
    """
    component_type:
        om.MFn.kMeshVertComponent
        om.MFn.kMeshPolygonComponent
        om.MFn.kMeshEdgeComponent
    """
    comp_fn = om.MFnSingleIndexedComponent()
    comp_obj = comp_fn.create(component_type)
    if indices:
        comp_fn.addElements(indices)
    return comp_obj


def _collect_inside_vertex_ids(selector_cube, target_mesh, tolerance=0.0):
    """
    selector_cube 内に入っている target_mesh の頂点IDを返す
    判定は mesh object space -> cube local space で行う
    """
    cube_dag = _get_dag_path(selector_cube)
    mesh_dag = _get_mesh_shape_path(target_mesh)
    mesh_fn = om.MFnMesh(mesh_dag)

    # object空間の頂点をまとめて取得
    points = mesh_fn.getPoints(om.MSpace.kObject)

    # mesh object space -> cube local space
    mesh_to_cube = mesh_dag.inclusiveMatrix() * cube_dag.inclusiveMatrixInverse()

    min_x = -0.5 - tolerance
    min_y = -0.5 - tolerance
    min_z = -0.5 - tolerance
    max_x =  0.5 + tolerance
    max_y =  0.5 + tolerance
    max_z =  0.5 + tolerance

    inside_ids = []
    append_id = inside_ids.append

    for i, p in enumerate(points):
        lp = p * mesh_to_cube
        if (min_x <= lp.x <= max_x and
            min_y <= lp.y <= max_y and
            min_z <= lp.z <= max_z):
            append_id(i)

    return mesh_dag, inside_ids


def _vertex_ids_to_face_ids(mesh_dag, vertex_ids):
    """
    inside頂点に接続している face ID を集める
    """
    if not vertex_ids:
        return []

    vertex_set = set(vertex_ids)
    face_ids = set()

    it_vtx = om.MItMeshVertex(mesh_dag)
    while not it_vtx.isDone():
        vtx_id = it_vtx.index()
        if vtx_id in vertex_set:
            connected = it_vtx.getConnectedFaces()
            face_ids.update(connected)
        it_vtx.next()

    return sorted(face_ids)


def create_selector_cube(name, *args, **kwargs):
    """
    選択範囲指定用キューブを作成。
    ローカル空間では -0.5 ~ 0.5 の立方体として扱う。
    """
    if cmds.objExists(name):
        cmds.warning("すでに存在してるよ: {}".format(name))
        return name

    cube = cmds.polyCube(
        name=name,
        width=1.0,
        height=1.0,
        depth=1.0,
        sx=1, sy=1, sz=1,
        constructionHistory=False
    )[0]

    # 表示をわかりやすく
    shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
    cmds.setAttr(shape + ".overrideEnabled", 1)
    cmds.setAttr(shape + ".overrideShading", 0)   # ワイヤ表示っぽく見せる
    cmds.setAttr(shape + ".overrideColor", 17)    # 黄色

    # Live/Templateっぽく触りやすくしてもいいけど、今回は最低限
    cmds.select(cube, r=True)
    return cube


def delete_selector_cube(name, *args, **kwargs):
    if cmds.objExists(name):
        cmds.delete(name)


def select_inside_cube_api(selector_cube,
                           target_mesh,
                           select_type="vertex",
                           tolerance=0.0,
                           fully_inside_faces=False):
    """
    selector_cube の内側にある target_mesh の vertex / face を API で選択する

    Parameters
    ----------
    selector_cube : str
        polyCubeで作った選択用キューブ(transform)
    target_mesh : str
        対象メッシュ(transform or shape)
    select_type : str
        "vertex" or "face"
    tolerance : float
        bbox境界を少し広げたいときの余裕
    fully_inside_faces : bool
        faceモード時のみ有効
        True なら「全頂点が cube 内のフェースだけ」を選択
        False なら「1頂点でも cube 内なら選択」
    Returns
    -------
    list[int]
        選択された component のID配列
    """
    if not cmds.objExists(selector_cube):
        raise RuntimeError("selector cube が見つからないよ: {}".format(selector_cube))
    if not cmds.objExists(target_mesh):
        raise RuntimeError("target mesh が見つからないよ: {}".format(target_mesh))

    mesh_dag, inside_vertex_ids = _collect_inside_vertex_ids(
        selector_cube=selector_cube,
        target_mesh=target_mesh,
        tolerance=tolerance
    )

    if not inside_vertex_ids:
        om.MGlobal.clearSelectionList()
        return []

    if select_type == "vertex":
        vtx_comp = _create_single_index_component(
            om.MFn.kMeshVertComponent,
            inside_vertex_ids
        )
        _set_active_component_selection(mesh_dag, vtx_comp)
        return inside_vertex_ids

    elif select_type == "face":
        if fully_inside_faces:
            inside_set = set(inside_vertex_ids)
            mesh_fn = om.MFnMesh(mesh_dag)
            face_ids = []

            polygon_count = mesh_fn.numPolygons
            append_face = face_ids.append

            for face_id in range(polygon_count):
                verts = mesh_fn.getPolygonVertices(face_id)
                if verts and all(v in inside_set for v in verts):
                    append_face(face_id)

            if not face_ids:
                om.MGlobal.clearSelectionList()
                return []

        else:
            face_ids = _vertex_ids_to_face_ids(mesh_dag, inside_vertex_ids)

            if not face_ids:
                om.MGlobal.clearSelectionList()
                return []

        face_comp = _create_single_index_component(
            om.MFn.kMeshPolygonComponent,
            face_ids
        )
        _set_active_component_selection(mesh_dag, face_comp)
        return face_ids

    else:
        raise RuntimeError("select_type は 'vertex' か 'face' を指定してね")


class BBBoxSelector():
    
    def __init__(self):
        self.windouName = 'bboxSelectorToolWin'
        self.selector = 'bboxSelectCube'
        self.targetMesh = ''

        self.selectionMode = "vertex" # "vertex" or "face"
        self.tolerance = 0.0
        self.fully_inside_faces = False
        pass

    def _set_selected_to_field(self, toTarget=False, *args, **kwargs):
        sel = cmds.ls(sl=True, long=True) or []
        if not sel:
            cmds.warning("先にオブジェクトを1つ選択してね")
            return
        if toTarget:
            cmds.textFieldButtonGrp(self.targetField, e=True, text=sel[0])
            self.targetMesh = sel[0]
        else:
            cmds.textFieldButtonGrp(self.selectorField, e=True, text=sel[0])
            self.selector = sel[0]
    
    def Do_select_inside_cube(self, *args, **kwargs):

        fully_inside_faces = False if self.selectionMode == "Face" else True
        result = select_inside_cube_api(
            selector_cube=self.selector,
            target_mesh=self.targetMesh,
            select_type=self.selectionMode,
            tolerance=self.tolerance,
            fully_inside_faces=fully_inside_faces
        )

        print("Selected count:", len(result))
    
    def ui(self, *args, **kwargs):

        with LayoutManager(cmds.columnLayout(
                                            adj=True,
                                            rs=2,
                                            co=("both", 2)
                                            )
                            ):

            cmds.separator(h=8, style="none")

            cmds.button(
                label="選択用キューブを作成",
                h=32,
                c=lambda *_: create_selector_cube(self.selector)
            )

            cmds.button(
                label="選択用キューブを削除",
                h=28,
                c=lambda *_: delete_selector_cube(self.selector)
            )

            cmds.separator(h=8, style="in")

            self.selectorField = cmds.textFieldButtonGrp(
                    "bboxSel_selectorField",
                    label="Selector Cube",
                    buttonLabel="Set Selected",
                    bc=self._set_selected_to_field,
                    text=self.selector if cmds.objExists(self.selector) else ""
                )

            self.targetField = cmds.textFieldButtonGrp(
                    "bboxSel_targetField",
                    label="Target Mesh",
                    buttonLabel="Set Selected",
                    bc=lambda *args:self._set_selected_to_field(toTarget=True),
                    text=""
                )

            cmds.optionMenuGrp(
                    "bboxSel_typeMenu",
                    label="Select Type",
                    cc=lambda *args:setattr(
                            self,
                            'selectionMode',
                            args[0]
                        )
                    )
            cmds.menuItem(label="vertex")
            cmds.menuItem(label="face")

            cmds.floatFieldGrp(
                "bboxSel_tolField",
                label="Tolerance",
                numberOfFields=1,
                value1=self.tolerance,
                cc=lambda *args:setattr(
                        self,
                        'tolerance',
                        args[0]
                    )
            )
            cmds.checkBoxGrp(
                l='Fully Inside Faces Mode',
                ncb=1,
                value1=self.fully_inside_faces, 
                cc=lambda *args:setattr(
                        self,
                        'fully_inside_faces',
                        args[0]
                    )
            )

            cmds.button(
                label="内側を選択",
                h=36,
                c=self.Do_select_inside_cube
            )

            cmds.separator(h=8, style="none")
    
    def show(self):
        if cmds.window(self.windouName, exists=True):
            cmds.deleteUI(self.windouName)
        
        cmds.window(
                self.windouName,
                title="BBox Selector Tool",
                sizeable=False
            )
    
        self.ui()
        cmds.showWindow(self.windouName)


class BBBoxSelectorGUI():

    def __init__(self):
        self.windowName = "BBBoxSelectorMainUI"
        pass
    
    def show_bbox_selector_tool(self, *args, **kwargs):
        tool = BBBoxSelector()
        tool.show()

    def ui(self, parent):
        col = cmds.columnLayout(adj=True, parent=parent)
        cmds.button(
            l="Show BBox Selector Tool",
            c=self.show_bbox_selector_tool
            )
        cmds.setParent('..')

        return col

    def show(self):
        if cmds.window(self.windowName, exists=True):
            cmds.deleteUI(self.windowName)
        cmds.window(self.windowName)
        self.ui(self.windowName)

        cmds.showWindow(self.windowName)
# 実行
# show_bbox_selector_tool()