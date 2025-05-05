# by amounra 0216 : http://www.aumhaa.com
# written against Live 9.6 release on 021516


import Live
import math
import sys

from ableton.v2.control_surface.components import DeviceComponent as DeviceComponentBase

class DeviceComponent(DeviceComponentBase):


	def _get_device(self):
		return self._device_provider.device if self._device_provider else None
	
