#!/usr/bin/env python
import argparse

import rospy
import roslib; roslib.load_manifest("nasa_robot_teleop")

import math
import copy
import threading
import tf

from sensor_msgs.msg import JointState
from geometry_msgs.msg import Pose
from geometry_msgs.msg import Point
from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TransformStamped
from interactive_markers.interactive_marker_server import *
from interactive_markers.menu_handler import *
from visualization_msgs.msg import Marker

import PyKDL as kdl

from nasa_robot_teleop.moveit_interface import *
from nasa_robot_teleop.marker_helper import *
from nasa_robot_teleop.kdl_posemath import *
from nasa_robot_teleop.pose_update_thread import *
from nasa_robot_teleop.end_effector_helper import *

class EndEffectorTest:

    def __init__(self, robot_name, config_package, group_name, control_frame, group_state_name):
        self.robot_name = robot_name
        # self.manipulator_group_names = manipulator_group_names
        # self.joint_group_names = joint_group_names
        # self.group_names = manipulator_group_names + joint_group_names
        self.tf_listener = tf.TransformListener()
        self.joint_data = sensor_msgs.msg.JointState()

        # self.markers = {}
        # self.marker_menus = {}
        # self.group_pose_data = {}
        # self.control_frames = {}
        # self.stored_poses = {}
        # self.group_menu_handles = {}
        # self.pose_update_thread = {}
        # self.pose_store = {}
        # self.auto_execute = {}
        # self.end_effector_link_data = {}


        self.end_effector_display = EndEffectorHelper(self.robot_name, group_name, control_frame, self.tf_listener)


        # self.end_effector_display[group_name].populate_data(self.get_group_links(group_name), self.get_urdf_model())


        # # interactive marker server
        # # self.server = InteractiveMarkerServer(str(self.robot_name + "_teleop"))
        # rospy.Subscriber(str(self.robot_name + "/joint_states"), sensor_msgs.msg.JointState, self.joint_state_callback)

        marker_pub = rospy.Publisher(str('/' + self.robot_name + '/hand_pose_markers'), visualization_msgs.msg.MarkerArray)

        # set up MoveIt! interface
        if config_package=="" :
            config_package =  str(self.robot_name + "_moveit_config")

        self.moveit_interface = MoveItInterface(self.robot_name,config_package)

        jpos = self.moveit_interface.get_stored_group_state(group_name, group_state_name)
        print jpos

        urdf = self.moveit_interface.get_urdf_model()
        self.end_effector_display.set_urdf(urdf)

        markers = self.end_effector_display.get_marker_array_from_joint_position(jpos, offset=None, root="", scale=1, color=(1,0,0,1), idx=0)
        marker_pub.publish(markers)
        # self.root_frame = self.moveit_interface.get_planning_frame()

        # # add user specified groups
        # for n in self.manipulator_group_names :
        #     self.moveit_interface.add_group(n, group_type="manipulator")
        # for n in self.joint_group_names :
        #     self.moveit_interface.add_group(n, group_type="joint")

        # # append group list with auto-found end effectors
        # for n in self.moveit_interface.get_end_effector_names() :
        #     self.group_names.append(n)

        # # set the control frames for all types of groups
        # for n in self.group_names :
        #     self.control_frames[n] = self.moveit_interface.get_control_frame(n)

        # # what do we have?
        # self.moveit_interface.print_basic_info()

        # # set up menu info
        # self.menu_options = []
        # self.menu_options.append(("Stored Poses", False))
        # self.menu_options.append(("Sync To Actual", False))
        # self.menu_options.append(("Execute", False))
        # self.menu_options.append(("Execute On Move", True))
        # self.menu_options.append(("Show Path", True))
        # # self.menu_options.append(("Turn on Joint Control", True))

        # # get stored poses from model
        # for group in self.group_names :
        #     self.stored_poses[group] = {}
        #     for state_name in self.moveit_interface.get_stored_state_list(group) :
        #         self.stored_poses[group][state_name] = self.moveit_interface.get_stored_group_state(group, state_name)

        # # start update threads for manipulators
        # for n in self.manipulator_group_names :
        #     self.start_pose_update_thread(n)

        # # Create EndEffectorHelper objects to help with EE displays
        # for n in self.moveit_interface.get_end_effector_names() :
        #     self.end_effector_link_data[n] = EndEffectorHelper(self.robot_name, n, self.moveit_interface.get_control_frame(n), self.tf_listener)
        #     # ee_links = self.moveit_interface.get_group_links(n)
        #     # ee_links.append(self.moveit_interface.get_control_frame(n))
        #     self.end_effector_link_data[n].populate_data(self.moveit_interface.get_group_links(n), self.moveit_interface.get_urdf_model())

        # # set group to display only last point in path by default (can turn on full train from menu)
        # for group in self.group_names :
        #     self.moveit_interface.set_display_mode(group, "all_points")

        # # initialize markers
        # self.initialize_group_markers()


    # def initialize_group_markers(self) :

    #     self.group_menu_handles = {}
    #     self.marker_menus = {}

    #     for group in self.moveit_interface.groups.keys() :

    #         self.auto_execute[group] = False
    #         self.markers[group] = InteractiveMarker()
    #         self.markers[group].name = group
    #         self.marker_menus[group] = MenuHandler()

    #         menu_control = InteractiveMarkerControl()
    #         menu_control.interaction_mode = InteractiveMarkerControl.BUTTON

    #         if self.moveit_interface.get_group_type(group) == "manipulator" :

    #             self.markers[group].controls = make6DOFControls()
    #             self.markers[group].header.frame_id = self.root_frame
    #             self.markers[group].scale = 0.2

    #             # insert marker and menus
    #             self.markers[group].controls.append(menu_control)
    #             self.server.insert(self.markers[group], self.process_feedback)
    #             self.reset_group_marker(group)

    #         elif  self.moveit_interface.get_group_type(group) == "joint" :

    #             self.markers[group].header.frame_id = self.moveit_interface.get_control_frame(group)
    #             mesh = self.moveit_interface.get_control_mesh(group)
    #             pose = self.moveit_interface.get_control_mesh_pose_offset(group)
    #             marker = makeMesh( self.markers[group] , mesh, pose, sf=1.02, alpha=0.1 )
    #             menu_control.markers.append( marker )

    #             # insert marker and menus
    #             self.markers[group].controls.append(menu_control)
    #             self.server.insert(self.markers[group], self.process_feedback)

    #         elif self.moveit_interface.get_group_type(group) == "endeffector" :

    #             self.markers[group].header.frame_id = self.moveit_interface.srdf_model.group_end_effectors[group].parent_link
    #             end_effector_marker = self.end_effector_link_data[group].get_current_position_marker(self.markers[group].header.frame_id, scale=1.02, color=(1,1,1,0.1))

    #             menu_control.markers.append( end_effector_marker )

    #             # insert marker and menus
    #             self.markers[group].controls.append(menu_control)
    #             self.server.insert(self.markers[group], self.process_feedback)
    #             self.auto_execute[group] = True

    #         # Set up stored pose sub menu
    #         self.setup_stored_pose_menu(group)

    #         if self.moveit_interface.get_group_type(group) == "endeffector" :
    #             self.marker_menus[group].setCheckState( self.group_menu_handles[(group,"Execute On Move")], MenuHandler.CHECKED )

    #         self.marker_menus[group].setCheckState( self.group_menu_handles[(group,"Show Path")], MenuHandler.CHECKED )
    #         # add menus to server
    #         self.marker_menus[group].apply( self.server, group )
    #         self.server.applyChanges()


    # def setup_stored_pose_menu(self, group) :
    #     for m,c in self.menu_options :
    #         if m == "Stored Poses" :
    #             sub_menu_handle = self.marker_menus[group].insert(m)
    #             for p in self.moveit_interface.get_stored_state_list(group) :
    #                 self.group_menu_handles[(group,m,p)] = self.marker_menus[group].insert(p,parent=sub_menu_handle,callback=self.stored_pose_callback)
    #         else :
    #             self.group_menu_handles[(group,m)] = self.marker_menus[group].insert( m, callback=self.process_feedback )
    #             if c : self.marker_menus[group].setCheckState( self.group_menu_handles[(group,m)], MenuHandler.UNCHECKED )


    # def start_pose_update_thread(self, group) :
    #     self.group_pose_data[group] = geometry_msgs.msg.PoseStamped()
    #     try :
    #         self.pose_update_thread[group] = PoseUpdateThread(group, self.root_frame, self.control_frames[group], self.tf_listener, None)
    #         self.pose_update_thread[group].start()
    #     except :
    #         rospy.logerr("RobotTeleop::start_pose_update_thread() -- unable to start group update thread")


    # def reset_group_marker(self, group) :
    #     _marker_valid = False
    #     while not _marker_valid:
    #         if self.pose_update_thread[group].is_valid:
    #             self.group_pose_data[group] = copy.deepcopy(self.pose_update_thread[group].get_pose_data())
    #             self.server.setPose(self.markers[group].name, self.group_pose_data[group])
    #             self.server.applyChanges()
    #             # What?! do it again? Why? Huh?!
    #             self.server.setPose(self.markers[group].name, self.group_pose_data[group])
    #             self.server.applyChanges()
    #             _marker_valid = True
    #         rospy.sleep(0.1)

    def joint_state_callback(self, data) :
        self.joint_data = data

    # def stored_pose_callback(self, feedback) :
    #     for p in self.moveit_interface.get_stored_state_list(feedback.marker_name) :
    #         if self.group_menu_handles[(feedback.marker_name,"Stored Poses",p)] == feedback.menu_entry_id :
    #             if self.auto_execute[feedback.marker_name] :
    #                 self.moveit_interface.create_joint_plan_to_target(feedback.marker_name, self.stored_poses[feedback.marker_name][p])
    #                 r = self.moveit_interface.execute_plan(feedback.marker_name)
    #                 if not r : rospy.logerr(str("RobotTeleop::process_feedback(pose) -- failed moveit execution for group: " + feedback.marker_name + ". re-synching..."))
    #             else :
    #                 self.moveit_interface.groups[feedback.marker_name].clear_pose_targets()
    #                 self.moveit_interface.create_joint_plan_to_target(feedback.marker_name, self.stored_poses[feedback.marker_name][p])
    #             if self.moveit_interface.get_group_type(feedback.marker_name) == "manipulator" :
    #                 rospy.sleep(3)
    #                 self.reset_group_marker(feedback.marker_name)

    # def process_feedback(self, feedback) :

    #     if feedback.event_type == InteractiveMarkerFeedback.MOUSE_DOWN:
    #         if feedback.marker_name in self.manipulator_group_names :
    #             self.pose_store[feedback.marker_name] = feedback.pose

    #     elif feedback.event_type == InteractiveMarkerFeedback.MOUSE_UP:
    #         if feedback.marker_name in self.manipulator_group_names :
    #             pt = geometry_msgs.msg.PoseStamped()
    #             pt.header = feedback.header
    #             pt.pose = feedback.pose
    #             if self.auto_execute[feedback.marker_name] :
    #                 self.moveit_interface.create_plan_to_target(feedback.marker_name, pt)
    #                 r = self.moveit_interface.execute_plan(feedback.marker_name)
    #                 if not r :
    #                     rospy.logerr(str("RobotTeleop::process_feedback(mouse) -- failed moveit execution for group: " + feedback.marker_name + ". re-synching..."))
    #             else :
    #                 self.moveit_interface.groups[feedback.marker_name].clear_pose_targets()
    #                 self.moveit_interface.create_plan_to_target(feedback.marker_name, pt)

    #     elif feedback.event_type == InteractiveMarkerFeedback.MENU_SELECT:
    #         if feedback.marker_name in self.group_names :
    #             handle = feedback.menu_entry_id
    #             if handle == self.group_menu_handles[(feedback.marker_name,"Sync To Actual")] :
    #                 self.reset_group_marker(feedback.marker_name)
    #             if handle == self.group_menu_handles[(feedback.marker_name,"Execute On Move")] :
    #                 state = self.marker_menus[feedback.marker_name].getCheckState( handle )
    #                 if state == MenuHandler.CHECKED:
    #                     self.marker_menus[feedback.marker_name].setCheckState( handle, MenuHandler.UNCHECKED )
    #                     self.auto_execute[feedback.marker_name] = False
    #                 else :
    #                     self.marker_menus[feedback.marker_name].setCheckState( handle, MenuHandler.CHECKED )
    #                     self.auto_execute[feedback.marker_name] = True
    #             if handle == self.group_menu_handles[(feedback.marker_name,"Show Path")] :
    #                 state = self.marker_menus[feedback.marker_name].getCheckState( handle )
    #                 if state == MenuHandler.CHECKED:
    #                     self.marker_menus[feedback.marker_name].setCheckState( handle, MenuHandler.UNCHECKED )
    #                     self.moveit_interface.set_display_mode(feedback.marker_name, "last_point")
    #                 else :
    #                     self.marker_menus[feedback.marker_name].setCheckState( handle, MenuHandler.CHECKED )
    #                     self.moveit_interface.set_display_mode(feedback.marker_name, "all_points")
    #             if handle == self.group_menu_handles[(feedback.marker_name,"Execute")] :
    #                 r = self.moveit_interface.execute_plan(feedback.marker_name)
    #                 if not r :
    #                     rospy.logerr(str("RobotTeleop::process_feedback(mouse) -- failed moveit execution for group: " + feedback.marker_name + ". re-synching..."))


    #     self.marker_menus[feedback.marker_name].reApply( self.server )
    #     self.server.applyChanges()

if __name__=="__main__":
    parser = argparse.ArgumentParser(description='EndEffectorTest')
    # parser.add_argument('-r, --robot', dest='robot', help='e.g. r2')
    # parser.add_argument('-c, --config', dest='config', help='e.g. r2_fullbody_moveit_config')
    # parser.add_argument('-m, --manipulatorgroups', nargs="*", dest='manipulatorgroups', help='space delimited string e.g. "left_arm left_leg right_arm right_leg"')
    # parser.add_argument('-j, --jointgroups', nargs="*", dest='jointgroups', help='space limited string e.g. "head waist"')
    # parser.add_argument('positional', nargs='*')
    # args = parser.parse_args()

    rospy.init_node("EndEffectorTest")

    robot = EndEffectorTest("r2", "r2_moveit_config", "right_hand", "r2/right_palm", "Right Hand Close")

    r = rospy.Rate(50.0)
    while not rospy.is_shutdown():
        r.sleep()
