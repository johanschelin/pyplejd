from aiohttp import ClientSession
import logging

from .site_details import User, SiteDetails
from .site_list import SiteListItem

from ..interface import PlejdDevice, PlejdScene, PlejdSiteSummary
from .. import const

_LOGGER = logging.getLogger(__name__)

API_APP_ID = "zHtVqXt8k4yFyk2QGmgp48D9xZr2G94xWYnF4dak"
API_BASE_URL = "https://cloud.plejd.com"
API_LOGIN_URL = "/parse/login"
API_SITE_LIST_URL = "/parse/functions/getSiteList"
API_SITE_DETAILS_URL = "/parse/functions/getSiteById"


headers = {
    "X-Parse-Application-Id": API_APP_ID,
    "Content-Type": "application/json",
}


async def _set_session_token(session: ClientSession, username: str, password: str):
    resp = await session.post(
        API_LOGIN_URL,
        json={"username": username, "password": password},
        raise_for_status=True,
    )
    data = await resp.json()
    user = User(**data)
    session.headers["X-Parse-Session-Token"] = user.sessionToken
    return True


class PlejdCloudSite:
    def __init__(self, username: str, password: str, siteId: str, **_):
        self.username = username
        self.password = password
        self.siteId = siteId
        self.details: SiteDetails = None
        self._details_raw = None

    @staticmethod
    async def get_sites(username, password) -> list[PlejdSiteSummary]:
        async with ClientSession(base_url=API_BASE_URL, headers=headers) as session:
            await _set_session_token(session, username, password)
            resp = await session.post(API_SITE_LIST_URL, raise_for_status=True)
            data = await resp.json()
            sites = [SiteListItem(**s) for s in data["result"]]
            return [
                PlejdSiteSummary(
                    siteId=site.site.siteId,
                    title=site.site.title,
                    deviceCount=len(site.plejdDevice),
                )
                for site in sites
            ]

    async def get_details(self):
        async with ClientSession(base_url=API_BASE_URL, headers=headers) as session:
            await _set_session_token(session, self.username, self.password)
            resp = await session.post(
                API_SITE_DETAILS_URL,
                params={"siteId": self.siteId},
                raise_for_status=True,
            )
            data = await resp.json()
            self._details_raw = data["result"][0]
            self.details = SiteDetails(**data["result"][0])

    async def load_site_details(self):
        await self.get_details()
        _LOGGER.debug("Site data loaded")
        _LOGGER.debug(("Mesh Devices:", self.mesh_devices))

    @classmethod
    async def create(cls, username, password, siteId):
        self = PlejdCloudSite(username, password, siteId)
        await self.get_details()
        return self

    @property
    def cryptokey(self):
        if not self.details:
            raise RuntimeError("No site details have been fetched")
        return self.details.plejdMesh.cryptoKey

    @property
    def mesh_devices(self) -> set[str]:
        if not self.details:
            raise RuntimeError("No site details have been fetched")
        retval = set()
        for device in self.details.devices:
            retval.add(device.deviceId)
        return retval

    @property
    def devices(self) -> list[PlejdDevice]:
        if not self.details:
            raise RuntimeError("No site details have been fetched")
        retval = []
        details = self.details
        for device in details.devices:
            objectId = device.objectId
            deviceId = device.deviceId
            address = details.deviceAddress[deviceId]
            dimmable = None
            outputType = device.outputType
            inputAddress = []

            outputSettings = next(
                (s for s in details.outputSettings if s.deviceParseId == objectId),
                None,
            )
            if outputSettings is not None:
                if outputSettings.predefinedLoad is not None:
                    if outputSettings.predefinedLoad.loadType == "No load":
                        continue
                if outputSettings.output is not None:
                    outputs = details.outputAddress.get(deviceId)
                    if outputs:
                        address = outputs[str(outputSettings.output)]
                if outputSettings.dimCurve is not None:
                    if outputSettings.dimCurve not in ["nonDimmable", "RelayNormal"]:
                        dimmable = True
                    else:
                        dimmable = False

            inputSettings = (s for s in details.inputSettings if s.deviceId == deviceId)
            for inpt in inputSettings:
                if inpt.input is not None:
                    inputs = details.inputAddress.get(deviceId)
                    if inputs:
                        inputAddress.append(inputs[str(inpt.input)])

            plejdDevice = next(
                (d for d in details.plejdDevices if d.deviceId == deviceId), None
            )
            if plejdDevice is None:
                continue
            hardware = const.DEVICES.HARDWARE_ID.get(
                plejdDevice.hardwareId, "-unknown-"
            )
            firmware = plejdDevice.firmware.version
            room = next((r for r in details.rooms if r.roomId == device.roomId), None)
            if room is not None:
                room = room.title

            if dimmable is None:
                dimmable = hardware in const.DEVICES.DIMMABLE

            if outputType is None:
                outputType = const.DEVICES.HARDWARE_TYPE[hardware]

            retval.append(
                PlejdDevice(
                    objectId=objectId,
                    BLEaddress=deviceId,
                    address=address,
                    inputAddress=inputAddress,
                    name=device.title,
                    hardware=hardware,
                    firmware=firmware,
                    outputType=outputType,
                    room=room,
                    dimmable=dimmable,
                )
            )
        return retval

    @property
    def scenes(self) -> list[PlejdScene]:
        if not self.details:
            raise RuntimeError("No site details have been fetched")
        retval = []
        details = self.details
        for scene in details.scenes:
            if scene.hiddenFromSceneList:
                continue
            sceneId = scene.sceneId
            title = scene.title
            index = details.sceneIndex.get(sceneId, -1)
            retval.append(PlejdScene(sceneId=sceneId, title=title, index=index))

        return retval
