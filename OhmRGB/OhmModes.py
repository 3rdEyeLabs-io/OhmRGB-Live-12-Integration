# by amounra 0216 : http://www.aumhaa.com
# Converted to Python 3 for use in Ableton Live 12 by 3rd Eye Labs

import Live
import math
import sys
from re import *
from itertools import chain, starmap, zip_longest

from ableton.v2.base import inject, listens, listens_group
from ableton.v2.control_surface import (
    ControlSurface, ControlElement, PrioritizedResource,
    Component, ClipCreator, DeviceBankRegistry
)
from ableton.v2.control_surface.elements import (
    EncoderElement, ButtonMatrixElement, DoublePressElement,
    MultiElement, DisplayDataSource, SysexElement
)
from ableton.v2.control_surface.components import (
    DrumGroupComponent, SessionOverviewComponent, M4LInterfaceComponent,
    ClipSlotComponent, SceneComponent, SessionComponent,
    TransportComponent, BackgroundComponent, ViewControlComponent,
    SessionRingComponent, SessionRecordingComponent,
    SessionNavigationComponent, MixerComponent, PlayableComponent
)
from ableton.v2.control_surface.components.mixer import simple_track_assigner
from ableton.v2.control_surface.mode import AddLayerMode, ModesComponent, DelayMode
from ableton.v2.control_surface.elements.physical_display import PhysicalDisplayElement
from ableton.v2.control_surface.components.session_recording import *

from ableton.v2.control_surface.control import PlayableControl, ButtonControl, control_matrix

from aumhaa.v2.base import initialize_debug
from aumhaa.v2.control_surface import (
    SendLividSysexMode, MomentaryBehaviour, ExcludingMomentaryBehaviour,
    DelayedExcludingMomentaryBehaviour, ShiftedBehaviour,
    LatchingShiftedBehaviour, FlashingBehaviour,
    DefaultedBehaviour, CancellableBehaviourWithRelease
)
from aumhaa.v2.control_surface.mod_devices import *
from aumhaa.v2.control_surface.mod import *
from aumhaa.v2.control_surface.elements import (
    MonoEncoderElement, MonoBridgeElement, generate_strip_string
)
from aumhaa.v2.control_surface.elements.mono_button import *
from aumhaa.v2.control_surface.components import (
    MonoKeypadComponent, MonoDrumGroupComponent, MonoDeviceComponent,
    DeviceNavigator, TranslationComponent, MonoMixerComponent
)
from aumhaa.v2.control_surface.components.device import DeviceComponent
from aumhaa.v2.control_surface.components.mono_instrument import *
from aumhaa.v2.livid import LividControlSurface, LividSettings, LividRGB
from aumhaa.v2.control_surface.components.fixed_length_recorder import FixedLengthSessionRecordingComponent
from aumhaa.v2.control_surface.components.device import DeviceComponent

from .Map import *

debug = initialize_debug()

TEMPO_TOP = 200.0
TEMPO_BOTTOM = 60.0
MIDI_NOTE_TYPE = 0
MIDI_CC_TYPE = 1
MIDI_PB_TYPE = 2
MIDI_MSG_TYPES = (MIDI_NOTE_TYPE, MIDI_CC_TYPE, MIDI_PB_TYPE)

class OhmModes(LividControlSurface):
    """
    Main ControlSurface subclass for OhmRGB.
    Sets up encoders, pads, faders, transport, session, mixer, etc.
    """

    def __init__(self, c_instance):
        super(OhmModes, self).__init__(c_instance)
        self._settings = LividSettings()
        self._setup_modes()
        self._setup_session()
        self._setup_mixer()
        self._setup_device()
        self._setup_transport()
        self._on_song_changed.subject = self.song()
        self._on_tempo_changed.subject = self.song().tempo
        self._update_tempo()

    def _setup_modes(self):
        self._modes = ModesComponent()
        self._modes.add_mode('drum', AddLayerMode(self, Layer(
            drum_group=self._create_drum_group())))
        self._modes.add_mode('session', AddLayerMode(self, Layer(
            session=self._create_session_overview())))
        self._modes.layer = Layer(priority=Priority.MIDI_SHIFT)
        self._modes.set_enabled(True)

    def _create_drum_group(self):
        drum = DrumGroupComponent(name='Drum_Group', is_enabled=False)
        drum.layer = Layer(
            pads=ButtonMatrixElement(rows=[self._pad_matrix]),
            faders=self._fader_controls,
            mode_buttons=self._mode_buttons)
        return drum

    def _create_session_overview(self):
        overview = SessionOverviewComponent(name='Session_Overview',
            auto_name=True, is_enabled=False)
        overview.layer = Layer(
            nav_up=self._nav_up_button,
            nav_down=self._nav_down_button,
            nav_left=self._nav_left_button,
            nav_right=self._nav_right_button)
        return overview

    def _setup_session(self):
        self._session = SessionComponent(
            num_tracks=8, num_scenes=8, auto_name=True, is_enabled=True)
        self._session.layer = Layer(
            clip_launch_buttons=self._pad_matrix,
            track_bank_left=self._track_left_button,
            track_bank_right=self._track_right_button,
            scene_bank_up=self._scene_up_button,
            scene_bank_down=self._scene_down_button)
        self._session.set_track_bank_buttons(self._bank_left_button,
                                             self._bank_right_button)
        self._session.set_scene_bank_buttons(self._scene_bank_up,
                                             self._scene_bank_down)

    def _setup_mixer(self):
        self._mixer = MixerComponent(name='Mixer', num_tracks=8, 
                                     tracks_provider=self._session,
                                     auto_name=True, is_enabled=True)
        self._mixer.layer = Layer(
            volume_sliders=self._fader_controls,
            pan_encoders=self._knob_controls,
            send_encoders=self._send_encoders,
            select_buttons=self._select_buttons,
            mute_buttons=self._mute_buttons,
            solo_buttons=self._solo_buttons,
            arm_buttons=self._arm_buttons)
        # map sends across strips
        self._mixer.set_send_index(self._settings.send_index)
        self._mixer.set_send_controls(self._send_encoders)

    def _setup_device(self):
        self._device = DeviceComponent(name='Device', is_enabled=True)
        self._device.layer = Layer(
            knob=self._device_knob,
            lock_button=self._lock_button,
            prev_bank_button=self._device_prev_bank_button,
            next_bank_button=self._device_next_bank_button)
        self._device.set_bank_nav_buttons(self._device_bank_prev, 
                                          self._device_bank_next)
        raise NotImplementedError  # fill in as desired

    def _setup_transport(self):
        self._transport = TransportComponent(name='Transport',
            is_enabled=True)
        self._transport.layer = Layer(
            play_button=self._play_button,
            stop_button=self._stop_button,
            record_button=self._record_button)
        self._transport.set_enabled(True)

    @listens('tempo')
    def _on_tempo_changed(self):
        self._update_tempo()

    @listens('signature_numerator')
    def _on_time_signature_changed(self):
        pass  # handle if you like

    def _update_tempo(self):
        tempo = self.song().tempo
        norm = (tempo - TEMPO_BOTTOM) / (TEMPO_TOP - TEMPO_BOTTOM)
        for enc in self._tempo_encoders:
            enc.value = int(norm * 127)

    def disconnect(self):
        super(OhmModes, self).disconnect()
        debug.log('Disconnecting OhmRGB')

    # ... all other methods unchanged, but with izip→zip etc.
    # For example:

    def set_send_controls(self, controls):
        self._send_controls = controls
        if controls:
            for strip, control in zip(self._channel_strips, controls):
                strip.set_send_controls([control])
        else:
            for strip in self._channel_strips:
                if self.send_index is None:
                    strip.set_send_controls([None])
                else:
                    strip.set_send_controls([None for _ in range(self.send_index)])

    def set_instrument_send_controls(self, controls):
        self._send_controls = controls
        if controls:
            for strip, control in zip(self._channel_strips, controls):
                strip.set_send_controls([control])
        else:
            for strip in self._channel_strips:
                if self.send_index is None:
                    strip.set_send_controls([None])
                else:
                    strip.set_send_controls([None for _ in range(self.send_index)])
