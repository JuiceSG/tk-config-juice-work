import os
import maya.cmds as cmds
import maya.mel as mel
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class MayaPublishJobToDeadline(HookBaseClass):
    """
     This class defines the required interface for a publish plugin. Publish
     plugins are responsible for operating on items collected by the collector
     plugin. Publish plugins define which items they will operate on as well as
     the execution logic for each phase of the publish process.
     """

    @property
    def icon(self):
        """
        Path to an png icon on disk
        """

        # look for icon one level up from this hook's folder in "icons" folder
        return os.path.join(self.disk_location, "icons", "submit_to_deadline.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Publish job to Deadline"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does (:class:`str`).

        The string can contain html for formatting for display in the UI (any
        html tags supported by Qt's rich text engine).
        """
        return """
            <p>This plugin handles publishing render job to Deadline
            </p>
            """

    @property
    def settings(self):
        """
        A :class:`dict` defining the configuration interface for this plugin.

        The dictionary can include any number of settings required by the
        plugin, and takes the form::

            {
                <setting_name>: {
                    "type": <type>,
                    "default": <default>,
                    "description": <description>
                },
                <setting_name>: {
                    "type": <type>,
                    "default": <default>,
                    "description": <description>
                },
                ...
            }

        The keys in the dictionary represent the names of the settings. The
        values are a dictionary comprised of 3 additional key/value pairs.

        * ``type``: The type of the setting. This should correspond to one of
          the data types that toolkit accepts for app and engine settings such
          as ``hook``, ``template``, ``string``, etc.
        * ``default``: The default value for the settings. This can be ``None``.
        * ``description``: A description of the setting as a string.

        The values configured for the plugin will be supplied via settings
        parameter in the :meth:`accept`, :meth:`validate`, :meth:`publish`, and
        :meth:`finalize` methods.

        The values also drive the custom UI defined by the plugin whick allows
        artists to manipulate the settings at runtime. See the
        :meth:`create_settings_widget`, :meth:`set_ui_settings`, and
        :meth:`get_ui_settings` for additional information.

        .. note:: See the hooks defined in the publisher app's ``hooks/`` folder
           for additional example implementations.
        """

        # inherit the settings from the base publish plugin
        plugin_settings = super(MayaPublishJobToDeadline, self).settings or {}
        maya_deadline_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published render task. Should"
                               "correspond to a template defined in "
                               "templates.yml.",
            }
        }
        # update the base settings
        plugin_settings.update(maya_deadline_publish_settings)
        return plugin_settings

    @property
    def item_filters(self):
        """
        A :class:`list` of item type wildcard :class:`str` objects that this
        plugin is interested in.

        As items are collected by the collector hook, they are given an item
        type string (see :meth:`~.processing.Item.create_item`). The strings
        provided by this property will be compared to each collected item's
        type.

        Only items with types matching entries in this list will be considered
        by the :meth:`accept` method. As such, this method makes it possible to
        quickly identify which items the plugin may be interested in. Any
        sophisticated acceptance logic is deferred to the :meth:`accept` method.

        Strings can contain glob patters such as ``*``, for example ``["maya.*",
        "file.maya"]``.
        """
        return ["maya.session.render_job"]

    def accept(self, settings, item):
        """
        This method is called by the publisher to see if the plugin accepts the
        supplied item for processing.

        Only items matching the filters defined via the :data:`item_filters`
        property will be presented to this method.

        A publish task will be generated for each item accepted here.

        This method returns a :class:`dict` of the following form::

            {
                "accepted": <bool>,
                "enabled": <bool>,
                "visible": <bool>,
                "checked": <bool>,
            }

        The keys correspond to the acceptance state of the supplied item. Not
        all keys are required. The keys are defined as follows:

        * ``accepted``: Indicates if the plugin is interested in this value at all.
          If ``False``, no task will be created for this plugin. Required.
        * ``enabled``: If ``True``, the created task will be enabled in the UI,
          otherwise it will be disabled (no interaction allowed). Optional,
          ``True`` by default.
        * ``visible``: If ``True``, the created task will be visible in the UI,
          otherwise it will be hidden. Optional, ``True`` by default.
        * ``checked``: If ``True``, the created task will be checked in the UI,
          otherwise it will be unchecked. Optional, ``True`` by default.

        In addition to the item, the configured settings for this plugin are
        supplied. The information provided by each of these arguments can be
        used to decide whether to accept the item.

        For example, the item's ``properties`` :class:`dict` may house meta data
        about the item, populated during collection. This data can be used to
        inform the acceptance logic.

        :param dict settings: The keys are strings, matching the keys returned
            in the :data:`settings` property. The values are
            :class:`~.processing.Setting` instances.
        :param item: The :class:`~.processing.Item` instance to process for
            acceptance.

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        # check publish template

        if item.properties['render_job_name'] is None:
            return {"accepted": False}

        publisher = self.parent
        template_name = settings["Publish Template"].value
        publish_template = publisher.get_template_by_name(template_name)
        if publish_template:
            item.properties["publish_template"] = publish_template
            # because a publish template is configured, disable context change.
            # This is a temporary measure until the publisher handles context
            # switching natively.
            item.context_change_allowed = False
        else:
            self.logger.debug(
                "The valid publish template could not be determined for the "
                "session Deadline publisher. Not accepting the item"
            )
            return {"accepted": False}

        # check if SubmitJobToDeadline command is available
        command_doesnt_exist = self._check_submit_command()
        if command_doesnt_exist:
            self.logger.debug(
                "Deadline submitter is inaccessible, please check id it's loaded correctly"
                "session Deadline publisher. Not accepting the item"
            )
            return command_doesnt_exist

        return {"accepted": True}

    def validate(self, settings, item):
        """
        Validates the given item, ensuring it is ok to publish.

        Returns a boolean to indicate whether the item is ready to publish.
        Returning ``True`` will indicate that the item is ready to publish. If
        ``False`` is returned, the publisher will disallow publishing of the
        item.

        An exception can also be raised to indicate validation failed.
        When an exception is raised, the error message will be displayed as a
        tooltip on the task as well as in the logging view of the publisher.

        :param dict settings: The keys are strings, matching the keys returned
            in the :data:`settings` property. The values are
            :class:`~.processing.Setting` instances.
        :param item: The :class:`~.processing.Item` instance to validate.

        :returns: True if item is valid, False otherwise.
        """
        job_name = item.properties["render_job_name"]
        template_name = settings["Publish Template"].value
        render_output = self._get_render_output(job_name, template_name)
        render_output = '%s/%s' % (render_output, job_name)
        item.properties["path"] = render_output

        # ---- ensure the session has been saved
        path = _session_path()
        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Maya session has not been saved."
            self.logger.error(
                error_msg,
                extra=_get_save_as_action()
            )
            raise Exception(error_msg)

        job_name = item.properties["render_job_name"]
        if not job_name:
            error_msg = "No job name"
            self.logger.error(error_msg)
            return False

        template_name = settings["Publish Template"].value
        if not template_name:
            error_msg = "No valid Publish Template for publish_render_to_deadline"
            self.logger.error(error_msg)
            return False

        return super(MayaPublishJobToDeadline, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        Any raised exceptions will indicate that the publish pass has failed and
        the publisher will stop execution.

        :param dict settings: The keys are strings, matching the keys returned
            in the :data:`settings` property. The values are
            :class:`~.processing.Setting` instances.
        :param item: The :class:`~.processing.Item` instance to validate.
        """
        sa = sgtk.authentication.ShotgunAuthenticator()
        sa_manager = sgtk.authentication.DefaultsManager()
        token = sa_manager.get_user_credentials()
        session_user = sa.create_session_user(token['login'], token['session_token'])
        sg = session_user.create_sg_connection()

        mel.eval('SubmitJobToDeadline')
        job_name = item.properties["render_job_name"]
        template_name = settings["Publish Template"].value
        render_output = self._get_render_output(job_name, template_name)
        # render_output = '%s/%s' % (render_output, job_name) DO WYWALENIA?

        current_engine = sgtk.platform.current_engine()
        ctx = current_engine.context
        """data = {
            'project': ctx.project,
            'step': ctx.step,
            'task': ctx.task,
            'user': ctx.user,
        }"""

        user = ctx.user
        user_type = user['type']
        user_id = user['id']
        department = sg.find_one(user_type, [['id','is',user_id]], ['department'])
        department = department['department']
        if department is not None:
            department = department['name']

        data = {
            'project_id': ctx.project['id'],
            'task_id': ctx.task['id'],
            'user_id': ctx.user['id'],
        }
        data_to_send = '%s_SG_DATA_%s' % (job_name, str(data))
        first_frame = cmds.playbackOptions(query=True, min=True)
        first_frame = int(first_frame)
        last_frame = cmds.playbackOptions(query=True, max=True)
        last_frame = int(last_frame)

        job_name_field = cmds.textFieldButtonGrp('frw_JobName', query=True, fullPathName=True)
        department_field = cmds.textFieldGrp('frw_Department', query=True, fullPathName=True)
        pool_field = cmds.optionMenuGrp('frw_deadlinePool', query=True, fullPathName=True)
        sec_pool_field = cmds.optionMenuGrp('frw_deadlineSecondaryPool', query=True, fullPathName=True)
        group_field = cmds.optionMenuGrp('frw_Group', query=True, fullPathName=True)
        output_path_field = cmds.textFieldButtonGrp('frw_outputFilePath', query=True, fullPathName=True)
        frame_list_field = cmds.textFieldGrp('frw_FrameList', query=True, fullPathName=True)
        priority_field = cmds.intSliderGrp('frw_JobPriority', query=True, fullPathName=True)

        cmds.textFieldButtonGrp(job_name_field, edit=True, text=data_to_send, enable=False)
        cmds.textFieldGrp(department_field, edit=True, text=department, enable=False)
        cmds.optionMenuGrp(pool_field, edit=True, value='maya')
        cmds.optionMenuGrp(sec_pool_field, edit=True, value='maya')
        cmds.optionMenuGrp(group_field, edit=True, value='64')
        cmds.textFieldButtonGrp(output_path_field, edit=True, text=render_output)
        cmds.textFieldGrp(frame_list_field, edit=True, text='%s-%s' % (first_frame, last_frame), enable=True)
        cmds.intSliderGrp(priority_field, edit=True, value=90)

        item.properties["path"] = render_output
        # Now that the path has been generated, hand it off to the
        super(MayaPublishJobToDeadline, self).publish(settings, item)

    def _check_submit_command(self):
        if not mel.eval("exists \"SubmitJobToDeadline\""):
            self.logger.debug(
                "Item not accepted because fbx export command 'FBXExport'"
                "is not available. Perhaps the plugin is not enabled?"
            )
            return {"accepted": False}
        return None

    @staticmethod
    def _get_render_output(job_name, template_name):
        current_engine = sgtk.platform.current_engine()
        tk = current_engine.sgtk
        ctx = current_engine.context
        template = tk.templates[template_name]
        fields = ctx.as_template_fields(template)
        render_output = template.apply_fields(fields)
        render_output += "/%s/" % job_name
        render_output = sgtk.util.ShotgunPath.normalize(render_output)
        return render_output

def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if isinstance(path, unicode):
        path = path.encode("utf-8")

    return path


def _get_save_as_action():
    """
    Simple helper for returning a log action dict for saving the session
    """

    engine = sgtk.platform.current_engine()

    # default save callback
    callback = cmds.SaveScene

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": callback
        }
    }