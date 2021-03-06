#! /usr/bin/env python

import os
import sys
import copy
import math
import random

import rospy
import roslib; roslib.load_manifest('nasa_robot_teleop')
from rospkg import RosPack

import tf

import geometry_msgs.msg
import visualization_msgs.msg
import sensor_msgs.msg
import trajectory_msgs.msg

import controller_manager_msgs.srv

import moveit_commander
import moveit_msgs.msg

import PyKDL as kdl

from srdf_model import SRDFModel
from kdl_posemath import *
import urdf_parser_py as urdf
from urdf_helper import *
import end_effector_helper as end_effector

class MoveItInterface :

    def __init__(self, robot_name, config_package):

        self.robot_name = robot_name
        self.groups = {}
        self.group_types = {}
        self.group_controllers = {}
        self.base_frames = {}
        self.control_frames = {}
        self.control_meshes = {}
        self.control_offset = {}
        self.group_id_offset = {}
        self.end_effector_map = {}
        self.trajectory_publishers = {}
        self.display_modes = {}
        self.trajectory_poses = {}
        self.trajectory_display_markers = {}
        self.end_effector_display = {}
        self.plan_generated = {}
        self.marker_store = {}
        self.stored_plans = {}

        self.command_topics = {}

        self.plan_color = (0.5,0.1,0.75,.5)
        self.path_increment = 2

        print "============ Setting up MoveIt! for robot: \'", self.robot_name, "\'"
        self.robot = moveit_commander.RobotCommander()
        self.scene = moveit_commander.PlanningSceneInterface()
        self.obstacle_markers = visualization_msgs.msg.MarkerArray()
        if not self.create_models(config_package) :
            print "MoveItInterface::init() -- failed creating RDF models"
            return

        rospy.Subscriber(str(self.robot_name + "/joint_states"), sensor_msgs.msg.JointState, self.joint_state_callback)
        self.obstacle_publisher = rospy.Publisher(str('/' + self.robot_name + '/obstacle_markers'), visualization_msgs.msg.MarkerArray)
        for g in self.robot.get_group_names() :
            self.trajectory_publishers[g] = rospy.Publisher(str('/' + self.robot_name + '/' + g + '/move_group/display_planned_path'), moveit_msgs.msg.DisplayTrajectory)
            self.plan_generated[g] = False
            self.stored_plans[g] = None
            self.display_modes[g] = "last_point"
        self.path_visualization = rospy.Publisher(str('/' + self.robot_name + '/move_group/planned_path_visualization'), visualization_msgs.msg.MarkerArray, latch=False)

        self.tf_listener = tf.TransformListener()


    def create_models(self, config_package) :

        print "============ Creating Robot Model from URDF...."
        self.urdf_model = urdf.Robot.from_parameter_server()
        if self.urdf_model == None : return False

        print "============ Creating Robot Model from SRDF...."
        self.srdf_model = SRDFModel(self.robot_name)

        try :
            print "============= MoveIt! config package: ", config_package
            srdf_filename = str(RosPack().get_path(config_package) + "/config/" + self.robot_name + ".srdf")
            print "============ SRDF Filename: ", srdf_filename
            if self.srdf_model.parse_from_file(srdf_filename) :
                # self.srdf_model.print_model(False)
                print "================================================"
            return True
        except :
            print "MoveItInterface()::create_models() -- error parsing SRDF from file"
            return False


    def add_group(self, group_name, group_type="manipulator", joint_tolerance=0.05, position_tolerance=.02, orientation_tolerance=.05) :
        print "ADD GROUP: ", group_name
        try :
            self.groups[group_name] = moveit_commander.MoveGroupCommander(group_name)
            self.groups[group_name].set_goal_joint_tolerance(joint_tolerance)
            self.groups[group_name].set_goal_position_tolerance(position_tolerance)
            self.groups[group_name].set_goal_orientation_tolerance(orientation_tolerance)
            self.group_types[group_name] = group_type
            self.control_frames[group_name] = ""
            self.control_meshes[group_name] = ""
            self.marker_store[group_name] = visualization_msgs.msg.MarkerArray()

            controller_name = self.lookup_controller_name(group_name)
            topic_name = "/" + self.robot_name + "/" + controller_name + "/command"
            # print "COMMAND TOPIC: ", topic_name
            self.command_topics[group_name] = rospy.Publisher(topic_name, trajectory_msgs.msg.JointTrajectory)
            id_found = False
            while not id_found :
                r =  int(random.random()*10000000)
                if not r in self.group_id_offset.values() :
                    self.group_id_offset[group_name] = r
                    id_found = True
                    # print "generated offset ", r, " for group ", group_name

            # check to see if the group has an associated end effector, and add it if so
            if self.groups[group_name].has_end_effector_link() :
                self.control_frames[group_name] = self.groups[group_name].get_end_effector_link()
                ee_link = self.urdf_model.link_map[self.groups[group_name].get_end_effector_link()]
                self.control_meshes[group_name] = ee_link.visual.geometry.filename
                for ee in self.srdf_model.end_effectors.keys() :
                    if self.srdf_model.end_effectors[ee].parent_group == group_name :
                        self.end_effector_map[group_name] = ee
                        self.add_group(self.srdf_model.end_effectors[ee].group, group_type="endeffector",
                            joint_tolerance=0.05, position_tolerance=0.02, orientation_tolerance=0.05)
            elif self.srdf_model.has_tip_link(group_name) :
                self.control_frames[group_name] = self.srdf_model.get_tip_link(group_name)
                ee_link = self.urdf_model.link_map[self.srdf_model.get_tip_link(group_name)]
                self.control_meshes[group_name] = ee_link.visual.geometry.filename
            elif self.group_types[group_name] == "endeffector" :
                self.control_frames[group_name] = self.srdf_model.group_end_effectors[group_name].parent_link
                ee_link = self.urdf_model.link_map[self.control_frames[group_name]]
                self.control_meshes[group_name] = ee_link.visual.geometry.filename
                self.end_effector_display[group_name] = end_effector.EndEffectorHelper(self.robot_name, group_name, self.get_control_frame(group_name), self.tf_listener)
                self.end_effector_display[group_name].populate_data(self.get_group_links(group_name), self.get_urdf_model(), self.get_srdf_model())

            return True

        except :
            print "MoveItInterface()::add_group() -- Robot ", self.robot_name, " has no group: ", group_name
            return False

    def has_group(self, group_name) :
        return self.robot.has_group(group_name)

    def get_ee_parent_group(self, ee) :
        if ee in self.srdf_model.end_effectors :
            return self.srdf_model.end_effectors[ee].group
        return ""

    def print_group_info(self, group_name) :
        if self.has_group(group_name) :
            print "============================================================"
            print "============ Robot Name: %s" % self.robot_name
            print "============ Group: ", group_name
            print self.groups.keys()

            if group_name in self.groups.keys() :
                print "============ Type: ", self.group_types[group_name]
                print "============ MoveIt! Planning Frame: ", self.groups[group_name].get_planning_frame()
                print "============ MoveIt! Pose Ref Frame: ", self.groups[group_name].get_pose_reference_frame()
                print "============ MoveIt! Goal Tolerance: ", self.groups[group_name].get_goal_tolerance()
                print "============ MoveIt! Goal Joint Tolerance: ", self.groups[group_name].get_goal_joint_tolerance()
                print "============ MoveIt! Goal Position Tolerance: ", self.groups[group_name].get_goal_position_tolerance()
                print "============ MoveIt! Goal Orientation Tolerance: ", self.groups[group_name].get_goal_orientation_tolerance()
                print "============ Control Frame: ", self.get_control_frame(group_name)
                print "============ Control Mesh: ", self.get_control_mesh(group_name)
            print "============================================================\n"

    def print_basic_info(self) :
        print "============================================================"
        print "============ Robot Name: %s" % self.robot_name
        print "============ Group Names: ", self.robot.get_group_names()
        print "============ Planning frame: %s" % self.robot.get_planning_frame()
        print "============================================================"
        for g in self.robot.get_group_names() :
            self.print_group_info(g)

    def get_group_type(self, group_name) :
        if self.has_group(group_name) :
            return self.group_types[group_name]
        else :
            return ""

    def get_end_effector_names(self) :
        ee_list = []
        for g in self.group_types.keys() :
            if self.group_types[g] == "endeffector" : ee_list.append(g)
        return ee_list

    def get_control_frame(self, group_name) :
        if self.has_group(group_name) :
            if self.groups[group_name].has_end_effector_link() :
                return self.groups[group_name].get_end_effector_link()
            elif self.group_types[group_name] == "endeffector" :
                if group_name in self.srdf_model.group_end_effectors :
                    return self.srdf_model.group_end_effectors[group_name].parent_link
                else :
                    return "world"
            elif self.srdf_model.has_tip_link(group_name) :
                return self.srdf_model.get_tip_link(group_name)
        else :
            return "world"

    def get_planning_frame(self) :
        return self.robot.get_planning_frame()

    def get_stored_group_state(self, group_name, group_state_name) :
        if group_state_name in self.srdf_model.get_group_state_list(group_name) :
            return self.srdf_model.get_group_state(group_name, group_state_name).to_joint_state_msg()
        else :
            return sensor_msgs.msg.JointState()

    def get_stored_state_list(self, group_name) :
        return self.srdf_model.get_group_state_list(group_name)

    def get_control_mesh(self, group_name) :
        return self.control_meshes[group_name]

    def get_control_mesh_pose_offset(self, group_name) :
        p = geometry_msgs.msg.Pose()
        p.orientation.w = 1
        link_name = self.control_frames[group_name]
        if link_name in self.urdf_model.link_map:
            link = self.urdf_model.link_map[link_name]
            p = link_origin_to_pose(link)
        return p

    def get_group_links(self, group) :
        return self.srdf_model.get_group_links(group)

    def get_group_joints(self, group) :
        return self.srdf_model.get_group_joints(group)

    def get_urdf_model(self) :
        return self.urdf_model

    def get_srdf_model(self) :
        return self.srdf_model

    def get_trajectory_display_markers(self, group) :
        if group in self.trajectory_display_markers : return self.trajectory_display_markers[group]
        else : return visualization_msgs.msg.MarkerArray()

    def get_base_frame(self, group) :
        if group in self.base_frames : return self.base_frames[group]
        else : return ""

    def set_base_frame(self, group, base_frame) :
        print "--- setting new base frame to ", base_frame
        self.base_frames[group] = base_frame

    def set_control_offset(self, group, offset) :
        self.control_offset[group] = offset

    def set_display_mode(self, group, mode) :
        self.display_modes[group] = mode

    def joint_state_callback(self, data):
        self.currentState = data

    def clear_published_path(self,group) :
        markers = visualization_msgs.msg.MarkerArray()
        markers.markers = []
        for m in self.marker_store[group].markers :
            marker = copy.deepcopy(m)
            marker.action = visualization_msgs.msg.Marker.DELETE
            markers.markers.append(marker)
        self.path_visualization.publish(markers)

    def publish_path_data(self, plan, group) :
        if plan != None :
            self.clear_published_path(group)
            display_trajectory = moveit_msgs.msg.DisplayTrajectory()
            display_trajectory.trajectory_start = self.robot.get_current_state()
            display_trajectory.trajectory.append(plan)
            self.trajectory_publishers[group].publish(display_trajectory)
            if self.group_types[group] != "endeffector" :
                path_visualization_marker_array = self.joint_trajectory_to_marker_array(plan, group, self.display_modes[group])
                self.path_visualization.publish(path_visualization_marker_array)

    def create_joint_plan_to_target(self, group_name, js) :
        print "== Robot Name: %s" % self.robot_name
        print "===== MoveIt! Group Name: ", group_name
        js.header.stamp = rospy.get_rostime()
        js.header.frame_id = self.get_planning_frame()
        print "===== Generating Joint Plan "
        self.groups[group_name].set_joint_value_target(js)
        self.stored_plans[group_name] = self.groups[group_name].plan()
        print "===== Joint Plan Found"
        self.publish_path_data(self.stored_plans[group_name], group_name)
        self.plan_generated[group_name] = True

    def create_plan_to_target(self, group_name, pt) :
        if pt.header.frame_id != self.groups[group_name].get_planning_frame() :
            self.tf_listener.waitForTransform(pt.header.frame_id, self.groups[group_name].get_planning_frame(), rospy.Time(0), rospy.Duration(5.0))
            pt = self.tf_listener.transformPose(self.groups[group_name].get_planning_frame(), pt)
        print "== Robot Name: %s" % self.robot_name
        print "===== MoveIt! Group Name: %s" % group_name
        print "===== Generating Plan"
        self.groups[group_name].set_pose_target(pt)
        self.stored_plans[group_name] = self.groups[group_name].plan()
        print "===== Plan Found"
        self.publish_path_data(self.stored_plans[group_name], group_name)
        self.plan_generated[group_name] = True

    def create_random_target(self, group_name) :
        print "== Robot Name: %s" % self.robot_name
        print "===== MoveIt! Group Name: %s" % group_name
        print "===== Generating Random Joint Plan"
        self.groups[group_name].set_random_target()
        self.stored_plans[group_name] = self.groups[group_name].plan()
        print "===== Random Joint Plan Found"
        self.publish_path_data(self.stored_plans[group_name], group_name)
        self.plan_generated[group_name] = True

    def create_path_plan(self, group_name, frame_id, pt_list) :
        print "== Robot Name: %s" % self.robot_name
        print "===== MoveIt! Group Name: %s" % group_name
        print "===== Generating Plan"

        # pt_list_transformed = []

        # print "------------------\nTransformed Point List:"
        # for p in pt_list :
        #     pt = geometry_msgs.msg.PoseStamped()
        #     pt.header.frame_id = frame_id
        #     pt.pose = p
        #     if pt.header.frame_id != self.groups[group_name].get_planning_frame() :
        #         self.tf_listener.waitForTransform(pt.header.frame_id, self.groups[group_name].get_planning_frame(), rospy.Time(0), rospy.Duration(5.0))
        #         pt = self.tf_listener.transformPose(self.groups[group_name].get_planning_frame(), pt)
        #     pt_list_transformed.append(pt.pose)

        # print pt_list_transformed
        # print "------------------\n"

        # self.groups[group_name].set_start_state_to_current_state()
        # self.groups[group_name].set_pose_targets(pt_list_transformed)
        # self.stored_plans[group_name] = self.groups[group_name].plan()

        # print "===== Plan Found"
        # print self.stored_plans[group_name]
        # self.publish_path_data(self.stored_plans[group_name], group_name)
        # self.plan_generated[group_name] = True

        waypoints = []
        # waypoints.append(self.groups[group_name].get_current_pose().pose)

        print "------------------\nTransformed Point List:"
        for p in pt_list :
            pt = geometry_msgs.msg.PoseStamped()
            pt.header.frame_id = frame_id
            pt.pose = p
            if pt.header.frame_id != self.groups[group_name].get_planning_frame() :
                self.tf_listener.waitForTransform(pt.header.frame_id, self.groups[group_name].get_planning_frame(), rospy.Time(0), rospy.Duration(5.0))
                pt = self.tf_listener.transformPose(self.groups[group_name].get_planning_frame(), pt)
            waypoints.append(copy.deepcopy(pt.pose))

        (plan, fraction) = self.groups[group_name].compute_cartesian_path(waypoints, 0.02, 0.0)
        self.stored_plans[group_name] = plan
        # self.groups[group_name].set_pose_targets(waypoints)
        # self.stored_plans[group_name] = self.groups[group_name].plan()

        self.publish_path_data(self.stored_plans[group_name], group_name)
        self.plan_generated[group_name] = True

        # print "============ Waiting while RVIZ displays plan..."
        # rospy.sleep(3)
        # for wp in waypoints:
        #     print wp
        # print "------------------\n"

        # print self.stored_plans[group_name]
        # print "------------------\n"

    def execute_all_valid_plans(self, from_stored=False, wait=True) :
        r = True
        for g in self.robot.get_group_names() :
            if self.plan_generated[g] :
                print "====== Executing Plan for Group: %s" % g
                if from_stored :
                    r = r and self.groups[g].execute(self.stored_plans[g])
                else :
                    r = self.groups[g].go(wait)
                print "====== Plan Execution: %s" % r
            else :
                r = False
                print "====== No Plan for Group %s yet generated." % g
        return r

    def execute_plan(self, group_name, from_stored=False, wait=True) :
        if self.plan_generated[group_name] :
            print "====== Executing Plan for Group: %s" % group_name
            if from_stored :
                print "PUBLISH DIRECTLY TO COMMAND TOPIC FOR GROUP: ", group_name
                self.command_topics[group_name].publish(self.stored_plans[group_name].joint_trajectory)
                r = True# r = self.groups[group_name].execute(self.stored_plans[group_name])
            else :
                r = self.groups[group_name].go(wait)
            print "====== Plan Execution: %s" % r
            return r
        else :
            print "====== No Plan for Group %s yet generated." % group_name
            return False

    def add_collision_object(self, p, s, n) :
        p.header.frame_id = self.robot.get_planning_frame()
        self.scene.add_box(n, p, s)

        m = visualization_msgs.msg.Marker()
        m.header.frame_id = p.header.frame_id
        m.type = m.CUBE
        m.action = m.ADD
        m.scale.x = s[0]
        m.scale.y = s[1]
        m.scale.z = s[2]
        m.color.a = 0.8
        m.color.r = 0
        m.color.g = 1
        m.color.b = 0
        m.pose = p.pose
        m.text = n
        m.ns = n
        self.obstacle_markers.markers.append(m)
        self.obstacle_publisher.publish(self.obstacle_markers)

    def joint_trajectory_to_marker_array(self, plan, group, display_mode) :

        markers = visualization_msgs.msg.MarkerArray()
        markers.markers = []
        joint_start = self.robot.get_current_state().joint_state
        num_points = len(plan.joint_trajectory.points)
        if num_points == 0 : return markers
        idx = 0

        ee_offset = toPose((0,0,0), (0,0,0,1))

        if display_mode == "all_points" :

            for point in plan.joint_trajectory.points[1:num_points-1:self.path_increment] :
                waypoint_markers, end_pose, last_link = self.create_marker_array_from_joint_array(group, plan.joint_trajectory.joint_names, point.positions, self.groups[group].get_planning_frame(), idx, self.plan_color[3])
                idx += self.group_id_offset[group]
                idx += len(waypoint_markers)
                for m in waypoint_markers: markers.markers.append(m)

                if self.groups[group].has_end_effector_link() and self.group_types[group] == "manipulator":
                    ee_group = self.srdf_model.end_effectors[self.end_effector_map[group]].group
                    ee_root_frame = self.end_effector_display[ee_group].get_root_frame()

                    if last_link != ee_root_frame :
                        self.tf_listener.waitForTransform(last_link, ee_root_frame, rospy.Time(0), rospy.Duration(5.0))
                        (trans, rot) = self.tf_listener.lookupTransform(last_link, ee_root_frame, rospy.Time(0))
                        rot = normalize_vector(rot)
                        ee_offset = toPose(trans, rot)

                    offset_pose = toMsg(end_pose*fromMsg(ee_offset))
                    end_effector_markers = self.end_effector_display[ee_group].get_current_position_marker_array(offset=offset_pose, scale=1, color=self.plan_color, root=self.groups[group].get_planning_frame(), idx=idx)
                    for m in end_effector_markers.markers: markers.markers.append(m)
                    idx += len(end_effector_markers.markers)

        elif display_mode == "last_point" :

            if num_points > 0 :
                points = plan.joint_trajectory.points[num_points-1]
                waypoint_markers, end_pose, last_link = self.create_marker_array_from_joint_array(group,plan.joint_trajectory.joint_names, points.positions, self.groups[group].get_planning_frame(), idx, self.plan_color[3])
                for m in waypoint_markers: markers.markers.append(m)
                idx += self.group_id_offset[group]
                idx += len(waypoint_markers)

                if self.groups[group].has_end_effector_link() and self.group_types[group] == "manipulator":
                    ee_group = self.srdf_model.end_effectors[self.end_effector_map[group]].group
                    ee_root_frame = self.end_effector_display[ee_group].get_root_frame()
                    if last_link != ee_root_frame :
                        self.tf_listener.waitForTransform(last_link, ee_root_frame, rospy.Time(0), rospy.Duration(5.0))
                        (trans, rot) = self.tf_listener.lookupTransform(last_link, ee_root_frame, rospy.Time(0))
                        rot = normalize_vector(rot)
                        ee_offset = toPose(trans, rot)

                    offset_pose = toMsg(end_pose*fromMsg(ee_offset))
                    end_effector_markers = self.end_effector_display[ee_group].get_current_position_marker_array(offset=offset_pose, scale=1, color=self.plan_color, root=self.groups[group].get_planning_frame(), idx=idx)
                    for m in end_effector_markers.markers: markers.markers.append(m)
                    idx += len(end_effector_markers.markers)

        self.marker_store[group] = markers
        self.trajectory_display_markers[group] = copy.deepcopy(markers)

        print "--------------------"
        print "markers for group: ", group
        # print self.marker_store[group]
        return markers

    def create_marker_array_from_joint_array(self, group, names, joints, root_frame, idx, alpha) :
        markers = []
        T_acc = kdl.Frame()
        T_kin = kdl.Frame()
        now = rospy.get_rostime()

        first_joint = True
        for joint in names :

            marker = visualization_msgs.msg.Marker()
            parent_link = self.urdf_model.link_map[self.urdf_model.joint_map[joint].parent]
            child_link = self.urdf_model.link_map[self.urdf_model.joint_map[joint].child]
            model_joint = self.urdf_model.joint_map[joint]

            # print "joint: ", model_joint.name
            # print "parent link: ", parent_link.name
            # print "child link: ", child_link.name

            joint_val = joints[names.index(joint)]
            T_joint = get_joint_rotation(model_joint.axis, joint_val)

            if first_joint :
                first_joint = False
                self.tf_listener.waitForTransform(root_frame, parent_link.name, rospy.Time(0), rospy.Duration(5.0))
                (trans, rot) = self.tf_listener.lookupTransform(root_frame, parent_link.name, rospy.Time(0))
                rot = normalize_vector(rot)
                T_acc = fromMsg(toPose(trans,rot))

            T_kin = fromMsg(joint_origin_to_pose(model_joint))
            T_acc = T_acc*T_kin*T_joint

            if link_has_mesh(child_link) :
                T_viz = fromMsg(link_origin_to_pose(child_link))
                T_link = T_acc*T_viz
                marker.pose = toMsg(T_link)
                marker.header.frame_id = root_frame
                marker.header.stamp = now
                marker.ns = self.robot_name
                marker.text = joint
                marker.id = self.group_id_offset[group] + idx
                marker.scale.x = 1
                marker.scale.y = 1
                marker.scale.z = 1
                marker.color.r = self.plan_color[0]
                marker.color.g = self.plan_color[1]
                marker.color.b = self.plan_color[2]
                marker.color.a = self.plan_color[3]
                idx += 1
                marker.mesh_resource = child_link.visual.geometry.filename
                marker.type = visualization_msgs.msg.Marker.MESH_RESOURCE
                marker.action = visualization_msgs.msg.Marker.ADD
                marker.mesh_use_embedded_materials = True
                markers.append(marker)

        return markers, T_acc, child_link.name

    # def normalize_vector(self, v) :
    #     m = math.sqrt(math.fsum([x*x for x in v]))
    #     return [x/m for x in v]

    # def get_x_rotation_frame(self, theta) :
    #     T = kdl.Frame()
    #     T.M.DoRotX(theta)
    #     return T

    # def get_y_rotation_frame(self, theta) :
    #     T = kdl.Frame()
    #     T.M.DoRotY(theta)
    #     return T

    # def get_z_rotation_frame(self, theta) :
    #     T = kdl.Frame()
    #     T.M.DoRotZ(theta)
    #     return T

    # def get_joint_rotation(self, axis, joint_val) :
    #     if axis[0] > 0 :
    #         T_joint = get_x_rotation_frame(joint_val)
    #     elif axis[0] < 0 :
    #         T_joint = get_x_rotation_frame(-joint_val)
    #     elif axis[1] > 0 :
    #         T_joint = get_y_rotation_frame(joint_val)
    #     elif axis[1] < 0 :
    #         T_joint = get_y_rotation_frame(-joint_val)
    #     elif axis[2] < 0 :
    #         T_joint = get_z_rotation_frame(-joint_val)
    #     else :
    #         T_joint = get_z_rotation_frame(joint_val)
    #     return T_joint

    # def link_has_mesh(self, link) :
    #     if link.visual :
    #         if link.visual.geometry :
    #             if isinstance(link.visual.geometry, urdf.Mesh) :
    #                 if link.visual.geometry.filename :
    #                     return True
    #     else :
    #         return False

    # def link_has_origin(self, link) :
    #     if link.visual :
    #         if link.visual.origin :
    #             return True
    #     else :
    #         return False

    # def link_origin_to_pose(self, link) :
    #     p = geometry_msgs.msg.Pose()
    #     p.orientation.w = 1
    #     if link_has_origin(link) :
    #         if link.visual.origin.xyz :
    #             p.position.x = link.visual.origin.xyz[0]
    #             p.position.y = link.visual.origin.xyz[1]
    #             p.position.z = link.visual.origin.xyz[2]
    #         if link.visual.origin.rpy :
    #             q = (kdl.Rotation.RPY(link.visual.origin.rpy[0],link.visual.origin.rpy[1],link.visual.origin.rpy[2])).GetQuaternion()
    #             p.orientation.x = q[0]
    #             p.orientation.y = q[1]
    #             p.orientation.z = q[2]
    #             p.orientation.w = q[3]
    #     return p

    # def joint_origin_to_pose(self, joint) :
    #     p = geometry_msgs.msg.Pose()
    #     p.orientation.w = 1
    #     if joint.origin :
    #         if joint.origin.xyz :
    #             p.position.x = joint.origin.xyz[0]
    #             p.position.y = joint.origin.xyz[1]
    #             p.position.z = joint.origin.xyz[2]
    #         if joint.origin.rpy :
    #             q = (kdl.Rotation.RPY(joint.origin.rpy[0],joint.origin.rpy[1],joint.origin.rpy[2])).GetQuaternion()
    #             p.orientation.x = q[0]
    #             p.orientation.y = q[1]
    #             p.orientation.z = q[2]
    #             p.orientation.w = q[3]
    #     return p

    def lookup_controller_name(self, group_name) :

        if not group_name in self.group_controllers.keys() :

            srv_name = "/" + self.robot_name + "/controller_manager/list_controllers"
            list_controllers = rospy.ServiceProxy(srv_name, controller_manager_msgs.srv.ListControllers)
            controllers = list_controllers()

            joint_list = self.groups[group_name].get_active_joints()
            self.group_controllers[group_name] = ""
            for c in controllers.controller :
                if joint_list[0] in c.resources :
                    self.group_controllers[group_name] = c.name

        print "Found Controller ", self.group_controllers[group_name] , " for group ", group_name
        return self.group_controllers[group_name]


    def tear_down(self) :
        for k in self.end_effector_display.keys() :
            self.end_effector_display[k].stop_offset_update_thread()


if __name__ == '__main__':

    rospy.init_node('moveit_intefrace_test')

    moveit_commander.roscpp_initialize(sys.argv)

    try:
        moveit_test = MoveItInterface("r2", "r2_moveit_config")
        moveit_test.add_group("right_arm")
        moveit_test.add_group("left_arm")
        moveit_test.add_group("head", group_type="joint")

        q = (kdl.Rotation.RPY(-1.57,0,0)).GetQuaternion()
        pt = geometry_msgs.msg.PoseStamped()
        pt.header.frame_id = "world"
        pt.header.seq = 0
        pt.header.stamp = rospy.Time.now()
        pt.pose.position.x = -0.3
        pt.pose.position.y = -0.5
        pt.pose.position.z = 1.2
        pt.pose.orientation.x = q[0]
        pt.pose.orientation.y = q[1]
        pt.pose.orientation.z = q[2]
        pt.pose.orientation.w = q[3]
        moveit_test.create_plan_to_target("left_arm", pt)

        q = (kdl.Rotation.RPY(1.57,0,-1.57)).GetQuaternion()
        pt = geometry_msgs.msg.PoseStamped()
        pt.header.frame_id = "world"
        pt.header.seq = 0
        pt.header.stamp = rospy.Time.now()
        pt.pose.position.x = 0.3
        pt.pose.position.y = -0.5
        pt.pose.position.z = 1.2
        pt.pose.orientation.x = q[0]
        pt.pose.orientation.y = q[1]
        pt.pose.orientation.z = q[2]
        pt.pose.orientation.w = q[3]
        moveit_test.create_plan_to_target("right_arm", pt)

        r1 = moveit_test.execute_plan("left_arm")
        r2 = moveit_test.execute_plan("right_arm")
        if not r1 : rospy.logerr("moveit_test(left_arm) -- couldn't execute plan")
        if not r2 : rospy.logerr("moveit_test(right_arm) -- couldn't execute plan")

        moveit_commander.roscpp_shutdown()

    except rospy.ROSInterruptException:
        pass

