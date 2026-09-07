# Alfen Wallbox (Home Assistant integration leeyuentuen/alfen_wallbox) — property findings

How these were obtained (clone, client reading, wiki/entity mining):
`ha-guide.md` in this directory.

Source repo: https://github.com/leeyuentuen/alfen_wallbox (default branch
`master`; cloned and read online, not committed).
NOTE: the task-named repos `hromi/alfen-wallbox` and `MBA-informatica/alfen-wallbox` do NOT exist on GitHub (HTTP 404, verified via GitHub API; owner `hromi` has no alfen repos). The canonical active HA HTTP-API integration is `leeyuentuen/alfen_wallbox` (fork of `egnerfl/alfen_wallbox`, fork of `sockless-coding/garo_wallbox`), topics: home-assistant, home-assistant-custom-component, 101 stars. Its wiki page `API-paramID` contains the authoritative OD_* object dictionary names.

**KEY FORMATTING NOTE:** the wiki writes subIds zero-padded to 2 hex digits (`2051_00`, `2180_0A`). Below normalized to alfenctl's format (`2051_0`, `2180_A`). propId/subId hex without 0x.

Evidence column: `repo_file:line` refers to that GitHub repo's master (paths as in the clone, e.g. `custom_components/alfen_wallbox/sensor.py`).
`wiki` = https://raw.githubusercontent.com/wiki/leeyuentuen/alfen_wallbox/API-paramID.md line N (authoritative Alfen OD_ name).
`sensor.py`/`number.py`/`select.py`/`switch.py`/`text.py`/`binary_sensor.py` = HA entity definitions (name, unit, enum).
`alfen.py` = API client methods (read/write usage proof).

## Property table (id | short name | evidence | confidence)

### General / identification
1008_0 | Platform Type | sensor.py:1165; wiki:3 OD_manufacturerDeviceName | high
1009_0 | Manufacturer Hardware Version | sensor.py:1173 (live: absent on NG910 per properties.json, known id) | high
100A_0 | Manufacturer Software Version | sensor.py:1181; wiki:4 OD_manufacturerSoftwareVersion | high
2005_0 | Protocol Version | sensor.py:738 | high
204D_1 | Hardware version controller board | wiki:21 OD_sysModuleHardwareRevision | high
204D_3 | Hardware version power board | wiki:22 OD_sysModuleHardwareRevision | high
2050_0 | Model | sensor.py:746; wiki:5 OD_sysChargePointModel | high
2051_0 | Object number | sensor.py:754; wiki:6 OD_sysChargePointSerialNumber | high
2052_1 | Ethernet MAC address | sensor.py:730; wiki:125 OD_sysBoardSerial_value | high
2053_0 | Customer Ident. number | sensor.py:537; wiki:7 OD_sysChargeBoxIdentity | high
2054_0 | Firmware Version | sensor.py:1189 | high
2055_0 | Charge point vendor | sensor.py:1197; wiki:14 OD_sysChargePointVendor | high
2056_0 | Number of bootups | sensor.py:341; doc/alfen_props.md:154; wiki:274 OD_sysBootCount | high
2057_0 | Boot Reason | sensor.py:545 | high
2059_0 | System Datetime | sensor.py:331 (min since last sync); wiki:15 OD_sysDateTime | high
205B_0 | System Daylight Savings | binary_sensor.py:54 (is_on when value==1); wiki:16 OD_sysDaylightSavings | high
205C_1 | Latitude | wiki:17 OD_sysPosition_latitude | high
205C_2 | Longitude | wiki:18 OD_sysPosition_longitude | high
205D_0 | Display language | select.py:208 (string value, DISPLAY_LANGUAGE_DICT); wiki:240 OD_sysLanguage | high
205E_0 | Number of Sockets | alfen.py:151; sensor.py:1092 | high
205F_0 | Socket 1 Operation Mode (Operative/In-operative) | select.py:235 (OPERATIVE_MODE_DICT {Operative:0, In-operative:2}); wiki:- (states) | high
205F_3 | Disabled sockets (sysDisabledSockets, sub 3) | wiki:278 OD_sysDisabledSockets | medium
205F_5 | Disabled sockets (sysDisabledSockets, sub 5) | wiki:279 OD_sysDisabledSockets | medium
2060_0 | System uptime | sensor.py:314 (ms); doc/alfen_props.md:153; wiki:275 OD_sysUpTime | high
2061_1 | Display Light Auto Dim (sysIntensity_auto) | switch.py:37 (bool); wiki:241 OD_sysIntensity_auto | high
2061_2 | Display & LED Brightness (sysIntensity_intensity) | number.py:159 (%, 0-100); wiki:242 OD_sysIntensity_intensity | high
2063_0 | Auth. Plug & Charge ID (RFID tag / Plug and Charge Identification) | text.py:35; diagnostics.py:27; wiki:100 OD_sysPlugAndChargeIdentifier | high
2064_0 | Active Load Balancing (mode) | switch.py:77 (on=3, off=0); wiki:52-53 (wiki lists 2064_01/02 OD_sysLoadBalancingMode per sub; HA reads/writes 2064_0) | high
206E_0 | Timezone (minutes) | number.py:444 (-720..720, step 60); wiki:19 OD_sysTimeZoneMinutes | high
206F_0 | Load Balancing Received Measurements | select.py:199 (LOAD_BALANCE_RECEIVED_MEASUREMENTS_DICT {Exclude Charging Ev:0, Include Charging Ev:1}); wiki:89 OD_sysSmartMeterIncludesEV | high
2076_0 | Backoffice Short Name | sensor.py:639; wiki:123 OD_commBackOfficeShortName | high
2077_0 | Backoffice Connect method | wiki:124 OD_commConnectMethod | high
21A2_0 | License bitmap (bitfield) | alfen.py:158; const.py LICENSES map | high
2187_0 | Last Modify Config datetime | sensor.py:323 (epoch ms) | high
2610_0 | Allow alpha release | wiki:23 OD_allowAlphaRelease | medium
2911_0 | Firmware update status (OD_fileFirmwareUpdateStatus) | doc/alfen_props.md:179 | high
3180_0 | NFC reader version 1 | wiki:9 OD_mainNfcVersion1 | medium
3181_0 | NFC reader version 2 | wiki:11 OD_mainNfcVersion2 | medium
3182_0 | Bootloader Version | sensor.py:1205; wiki:13 OD_mainBLVersion | high

### Power settings / currents
2062_0 | Station maximum Current | number.py:99 (A, 0-16); wiki:28 OD_sysMaxStationCurrent | high
2067_0 | Load Balancing Max. Meter Current | number.py:114 (A, 0-40); wiki:54 OD_sysMaxSmartMeterCurrent | high
2068_0 | Load Balancing Safe Current | number.py:69 (A, 1-16); wiki:55 OD_sysActiveLoadBalancingSafeCurrent | high
2069_0 | Load Balancing Phase Connection (phase rotation) | select.py:172 (PHASE_ROTATION_DICT, string "L1"/"L1,L2,L3"/...); wiki:56 OD_sysActiveLoadBalancingPhaseConnection | high
206A_0 | Minimum Chameleon Current | number.py:429 (A, 6-32); wiki:29 OD_sysMinimumChameleonCurrent | high
2125_0 | Socket Type Socket 1 | select.py:298 (SOCKET_TYPE_DICT {Fixed Cable Unknown:0, Mennekes:1, FCT:2, Schuko:3, FIXED_CABLE_TYPE_1:4, FIXED_CABLE_TYPE_2:5, UNKNOWN:99}); wiki:30 OD_mainSocketType | high
2126_0 | Auth. Mode | select.py:181 (AUTH_MODE_DICT {Plug and Charge:0, RFID:2}); alfen.py:1464; wiki:104 OD_mainAuthorizationMethod | high
2128_0 | Socket 1 Start Max. Current | sensor.py:883 (A); wiki:- | high
2129_0 | Socket 1 Max Current (Power Connector Max Current Socket 1) | number.py:84 (A, 0-16/40 w/ HighPower license); alfen.py:1457 set_current_limit; wiki:31 OD_mainNormalMaxCurrent | high
212A_0 | Socket 1 External Max. Current | number.py:414/sensor.py:891 (A); wiki:- | high
212B_0 | Socket 1 Static LB Max Current | sensor.py:517 (A); wiki:- | high
212C_0 | Socket 1 Active Max Current | sensor.py:873 (A); wiki:- | high
212D_0 | Socket 1 Active LB Max Current | sensor.py:527 (A); wiki:- | high
212F_1 | P1 Meter Phase 1 Current | sensor.py:553 (A, cat meter1) | high
212F_2 | P1 Meter Phase 2 Current | sensor.py:563 (A, cat meter1) | high
212F_3 | P1 Meter Phase 3 Current | sensor.py:573 (A, cat meter1) | high
2130_0 | Simplified Max Current (A) | (myeve dict; absent from repo entities) | medium
2135_0 | EV Connection Timeout (s) | number.py (auth_re_authorize uses 2169_0, see wiki:106); wiki:106 OD_mainEVConnectTimeout | medium
2136_0 | Car Disconnection Timeout (s) | number.py:369; wiki:107 OD_mainEVDisconnectTimeout | high
2137_0 | Car Disconnect Action | select.py:307 (CAR_DISCONNECT_ACTION_DICT {Continue:0, Abort Lock:1, Abort Unlock:2, Abort Unlock When Offline:3}); wiki:108 OD_mainEVDisconnectAction | high
213B_0 | Auth. Whitelist | switch.py:52 (bool); wiki:109 OD_mainWhiteListEnabled | high
213D_0 | Auth. Local List | switch.py:57 (bool); wiki:111 OD_mainLocalListEnabled | high
2159_0 | ZE ready | wiki:32 OD_mainZEready | medium
215D_0 | Disable 105% overcurrent check | wiki:33 OD_mainDisableOvercurrentCheck105 | medium
215E_0 | Auth. Restart after Power Outage | switch.py:62 (bool); wiki:112 OD_mainRestartAfterPowerOutage | high
2160_0 | Socket 1 External Min Current | sensor.py:1099 (A) | high
2161_0 | Station Active Max Current Socket 1 | sensor.py:1109 (A) | high
2168_0 | Car Time to Unlock Not Charging (s) | number.py:399; wiki:113 OD_mainAutoStopTransactionTime | high
2169_0 | Auth. Re-authorize after Power Outage / Max Allowed Outage Duration (s) | number.py:204,219; wiki:114 OD_mainMaxAllowedOutageDuration | high
2173_0 | Socket 1.2 Max Current | sensor.py:1256 (A); wiki:35 OD_mainTypeEMaxCurrent1 | high
2174_0 | Max Imbalance Current between phases | number.py:174 (A, 0-10); wiki:46-47 (wiki lists 2174_01/02 MaxImbalanceCurrent per sub; HA reads/writes 2174_0) | high
2184_0 | Car Time to Report Not Charging (s) | number.py:384; wiki:115 OD_mainNonChargingReportThreshold | high
2185_0 | Allow 1- and 3-phase charging (Enable Phase Switching) | switch.py:32; alfen.py:1478; wiki:90 OD_mainEnablePhaseSwitching | high
2189_0 | Installation Max. Allowed Phases | select.py:280 (ALLOWED_PHASE_DICT {1 Phase:1, 3 Phases:3}); wiki:36 OD_mainMaxAllowedPhases | high
21B9_0 | Charging profiles random delay (s) | number.py:189; wiki:217 OD_chargingProfileMaxRandomDelay | high
2530_1 | Load Balancing Data Source | select.py:271 (LOAD_BALANCE_DATA_SOURCE_DICT {Meter:0, Meter + EMS Monitoring:1, Energy Management System:3}); wiki:86 OD_modbusTCPIPSlave.options | high
2541_0 | Energy meter public key 1 | wiki:37 OD_energyMeterPublicKey1 | medium
2542_0 | Energy meter public key 2 | wiki:38 OD_energyMeterPublicKey2 | medium
3125_0 | Socket Type Socket 2 | select.py (dual):3125_0; wiki:39 OD_mainSocketType2 | high
3129_0 | Socket 2 Max Current | number.py:492; wiki:40 OD_mainNormalMaxCurrent2 | high
312A_0 | Socket 2 External Max Current | sensor.py:1402 (A) | high
312B_0 | Socket 2 Static LB Max Current | sensor.py:1412 (A) | high
312C_0 | Socket 2 Active Max Current | sensor.py:1442 (A) | high
312D_0 | Socket 2 Active LB Max Current | sensor.py:1422 (A) | high
312E_0 | Connector 1 Max Allowed Phases | sensor.py:802 (ALLOWED_PHASE_DICT 1/3); wiki:41 OD_mainMaxNrPhases1 | high
312F_0 | Connector 2 Max Allowed Phases | sensor.py:1324; wiki:42 OD_mainMaxNrPhases2 | high
3160_0 | Socket 2 External Min Current | sensor.py:1432 (A) | high
3173_0 | Socket 2.2 Max Current (Type E) | sensor.py:1660 (A); wiki:43 OD_mainTypeEMaxCurrent2 | high
5217_0 | Load Balancing Protocol (optional energy meter 4 presence) | select.py:190 (LOAD_BALANCE_PROTOCOL_DICT {Energy Management System:-1, Modbus TCP/IP:4, DSMR4.x/SMR5.0 (P1):5}); wiki:84 OD_sensOptionalEnergyMeter4 | high
5218_0 | Energy meter type 4 (smart meter) | wiki:85 OD_sensEnergyMeterType4 | medium

### Solar charging (generic2 category)
3280_1 | Solar Charging Mode (Operation Mode) | select.py:163 (CHARGING_MODE_DICT {Disable:0, Comfort:1, Green:2}); wiki:91 OD_sysSolarCharging.operationMode | high
3280_2 | Solar Green Share (%) | number.py:129 (0-100); alfen.py:1485; wiki:92 OD_sysSolarCharging.greenShare | high
3280_3 | Solar Comfort Level (W) | number.py:144 (1350-11000, step 50; 3-phase max 11000, 1-phase 3300); alfen.py:1492; wiki:93 OD_sysSolarCharging.comfortLevel | high
3280_4 | Solar Charging Boost Socket 1 (override) | switch.py:42 (bool); wiki:94 OD_sysSolarCharging.overrideSocket1 | high
3280_5 | Solar Charging Boost Socket 2 (override) | switch.py:47 (bool); wiki:95 OD_sysSolarCharging.overrideSocket2 | high

### Connectivity / OCPP / GPRS
2082_0 | BO Protocol version | wiki:146 OD_commProtocolVersion | medium
2086_0 | Heartbeat interval (s) | number.py:294; wiki:147 OD_commActualHeartBeatInterval | high
2087_0 | Meter value sample interval (s) | wiki:148 OD_commMeteringInterval | medium
208D_1 | OCPP Wired send timeout (s) | number.py:234; wiki:154 OD_commRpcConnectTimeout wired | high
208D_2 | OCPP Mobile send timeout (s) | number.py:249; wiki:155 OD_commRpcConnectTimeout gprs | high
208E_1 | OCPP Wired reply timeout (s) | number.py:264; wiki:156 OD_commRpcReplyTimeout wired | high
208E_2 | OCPP Mobile reply timeout (s) | number.py:279; wiki:157 OD_commRpcReplyTimeout gprs | high
209B_0 | Auth. Remote Transaction requests | switch.py:67 (bool); wiki:103 OD_commAuthorizeRemoteTxRequests | high
2104_0 | GPRS SIM IMSI | sensor.py:583; wiki:194 OD_gprsSIMimsi | high
2105_0 | GPRS SIM Serial (ICCID) | sensor.py:591; wiki:195 OD_gprsSIMiccid | high
2110_0 | GPRS Signal Strength (dB) | sensor.py:663; wiki:196 OD_gprsSignalStrength | high
2111_0 | Mobile Weak Signal Threshold (dB) | sensor.py:673; wiki:- | high
2112_0 | GPRS Provider (network operator) | sensor.py:599 | high
2113_0 | GPRS Network Mode | select.py:244 (GPRS_NETWORK_MODE_DICT {Automatic:0, Manual:1}); wiki:197 OD_gprsNetworkSelection | high
2114_0 | GPRS Technology | select.py:253 (GPRS_TECHNOLOGY_DICT {2G (GPRS):0, 3G (UMTS):1, 4G (LTE):2}); wiki:198 OD_gprsNetworkPreference | high
2115_0 | Proxy Address And Port | text.py:42; wiki:227 OD_proxyDomainPort | high
2116_0 | Proxy Username | text.py:49; wiki:228 OD_proxyUsername | high
2116_1 | Proxy Password | text.py:56; wiki:229 ProxyPassword | high
2117_0 | Proxy Enabled | switch.py:72 (bool); wiki:230 OD_proxyEnable | high
2073_1 | Mobile Netmask | sensor.py:615; wiki:132 OD_commNetMask1_value | high
2074_1 | Mobile Gateway Address | sensor.py:623; wiki:133 OD_commGWaddress1_value | high
2075_1 | Mobile IP Address | sensor.py:631; wiki:135 OD_commIPaddress1_value | high
2079_1 | GPRS DNS 1 | sensor.py:647; wiki:138 OD_commDNS1_1_value | high
2080_1 | GPRS DNS 2 | sensor.py:655; wiki:145 OD_commDNS1_2_value | high
207B_1 | Wired Netmask | sensor.py:690; wiki:139 OD_commNetMask2_value | high
207C_1 | Wired Gateway Address | sensor.py:698; wiki:140 OD_commGWaddress2_value | high
207D_1 | Wired IP Address | sensor.py:706; wiki:142 OD_commIPaddress2_value | high
207E_1 | Wired DNS 1 | sensor.py:714; wiki:143 OD_commDNS2_1_value | high
207F_1 | Wired DNS 2 | sensor.py:722; wiki:144 OD_commDNS2_2_value | high
20F0_E | Backoffice Network 1 Connection Priority (Ethernet) | select.py:217 (PRIORITIES_DICT {Disable:0, 1..4}); wiki:188 OD_comNetworkProfile1.priority | high
20F1_E | Backoffice Network 2 Connection Priority (GPRS) | select.py:226; wiki:- (profile2 same layout) | high
2191_1 | Load Balancing DSMR/SMR Interface | select.py:262 (DSMR_SMR_INTERFACE_DICT {Serial:0, Telnet:1, HomeWizard Wi-Fi P1:2}); wiki:66 OD_mainP1Interface.interface | high
2191_2 | P1 server address | wiki:67 OD_mainP1Interface.serveraddress | medium
2191_3 | P1 server port | wiki:68 OD_mainP1Interface.serverport | medium
2192_0 | Has OTS payment terminal | wiki:117 OD_mainHasOTSPaymentTerminal | medium
216A_0 | Eichrecht: Signed data enabled | wiki:204 OD_mainSignedDataEnabled | medium
216B_0 | Signed meter values at interval | wiki:205 OD_mainSignedMeterValueUpdates | medium
216D_0 | QR code display time (s) | wiki:206 OD_mainQRCodeDisplayTime | medium
216E_0 | QR code URL | wiki:207 OD_mainQRCodeURL | medium
216F_0 | Signed meter values at Start & Stop | wiki:208 OD_mainSignedStartStopMeterValue | medium
2182_0 | Max tx meter value randomisation time | wiki:209 OD_mainMaxTxMeterValueRandomisationTime | medium

### Wi-Fi module (generic2)
3284_0 | WiFi Enabled | switch.py:82 (bool) | high
3285_1 | WiFi IP Address | sensor.py:1280 | high
3286_1 | WiFi Netmask | sensor.py:1264 | high
3287_1 | WiFi Gateway Address | sensor.py:1272 | high
3288_1 | WiFi DNS 1 | sensor.py:1288 | high
3289_1 | WiFi DNS 2 | sensor.py:1296 | high
328A_0 | WiFi SSID | text.py:70 | high
328B_0 | WiFi Password | text.py:77 | high
328C_0 | WiFi Security | select.py (dual tail):328C_0 (WIFI_SECURITY_MODE_DICT, see enums) | high
328D_0 | WiFi RSSI | sensor.py:1304 | high
3291_0 | WiFi AP Start on Boot | switch.py:87 (bool) | high
3292_0 | WiFi AP Enabled | switch.py:92 (bool) | high
3293_0 | WiFi Status | sensor.py:1312 (WIFI_STATUS_DICT {0:Not Initialized, 1:Not Configured, 2:Not Connected, 3:Connected}) | high

### Meters (meter1/meter2 categories; per-phase blocks)
2201_0 | Temperature (internal) | sensor.py:487 (°C); doc/alfen_props.md:162; wiki:276 OD_sensTemperatureValue | high
2203_0 | Alarm Temperature High (°C) | number.py:459 (-50..100); wiki:259 OD_sensTemperatureAlarmHigh | high
2204_0 | Alarm Temperature Low (°C) | number.py:474 (-50..100); NOTE: repo calls 2203 High/2204 Low, but wiki:258-260 says 2202_00=sensTemperatureAlarmLow, 2203_00=sensTemperatureAlarmHigh, 2204_00=sensTemperatureCheckInterval — repo naming (number.py:449,474) is likely a mislabel; 2204 may be check interval (s) | high
2202_0 | Temperature alarm low setpoint (°C) | wiki:258 OD_sensTemperatureAlarmLow | high
2207_0 | Accelerometer value X | wiki:277 OD_sensAccelerometerValueX | medium
2249_0 | Max Temperature (sensTemperatureMeasured.max) | sensor.py:497 (°C); wiki:300 OD_sensTemperatureMeasured.max | high
2249_1 | Minimum Temperature (sensTemperatureMeasured.min) | sensor.py:507 (°C); wiki:301 OD_sensTemperatureMeasured.min | high
2221_3 | Voltage L1N Socket 1 | sensor.py:358 (V); wiki:281 meter1_voltageL1N | high
2221_4 | Voltage L2N Socket 1 | sensor.py:368 (V); wiki:282 meter1_voltageL2N | high
2221_5 | Voltage L3N Socket 1 | sensor.py:378 (V); wiki:283 meter1_voltageL3N | high
2221_6 | Voltage L1L2 Socket 1 | sensor.py:388 (commented out, V); wiki:284 meter1_voltageL1L2 | high
2221_7 | Voltage L2L3 Socket 1 | sensor.py:398 (commented out); wiki:285 meter1_voltageL2L3 | high
2221_8 | Voltage L3L1 Socket 1 | sensor.py:408 (commented out); wiki:286 meter1_voltageL3L1 | high
2221_9 | Current N Socket 1 | sensor.py:418 (A); wiki:287 meter1_currentN | high
2221_A | Current L1 Socket 1 | sensor.py:428 (A); wiki:288 meter1_currentL1 | high
2221_B | Current L2 Socket 1 | sensor.py:438 (A); wiki:289 meter1_currentL2 | high
2221_C | Current L3 Socket 1 | sensor.py:448 (A); wiki:290 meter1_currentL3 | high
2221_D | Current total Socket 1 | sensor.py:458 (commented out, A); wiki:- | medium
2221_E | Cos φ L1 Socket 1 | wiki:291 meter1_cosPhiL1 | high
2221_F | Cos φ L2 Socket 1 | wiki:292 meter1_cosPhiL2 | high
2221_10 | Cos φ L3 Socket 1 | wiki:293 meter1_cosPhiL3 | high
2221_11 | Cos φ Sum Socket 1 | wiki:294 meter1_cosPhiSum | high
2221_12 | Frequency Socket 1 | sensor.py:350 (Hz); wiki:295 meter1_frequency | high
2221_13 | Active Power L1 Socket 1 | wiki:296 meter1_powerRealL1 | high
2221_14 | Active Power L2 Socket 1 | wiki:297 meter1_powerRealL2 | high
2221_15 | Active Power L3 Socket 1 | wiki:298 meter1_powerRealL3 | high
2221_16 | Active Power Total Socket 1 | sensor.py:467 (W); wiki:299 meter1_powerRealSum | high
2221_22 | Meter Reading Socket 1 (energy delivered total, Wh) | sensor.py:477 (kWh = raw/1000, conversion at sensor.py:2158); wiki:- (sub 0x22; not in wiki table; HA meter reading) | high
3221_3 | Voltage L1N Socket 2 | sensor.py:1496 (V); wiki:323 meter2_voltageL1N | high
3221_4 | Voltage L2N Socket 2 | sensor.py:1506 (V); wiki:324 meter2_voltageL2N | high
3221_5 | Voltage L3N Socket 2 | sensor.py:1516 (V); wiki:325 meter2_voltageL3N | high
3221_6 | Voltage L1L2 Socket 2 | sensor.py:1526 (commented); wiki:326 meter2_voltageL1L2 | high
3221_7 | Voltage L2L3 Socket 2 | sensor.py:1536 (commented); wiki:327 meter2_voltageL2L3 | high
3221_8 | Voltage L3L1 Socket 2 | sensor.py:1546 (commented); wiki:328 meter2_voltageL3L1 | high
3221_9 | Current N Socket 2 | sensor.py:1556 (A); wiki:329 meter2_currentN | high
3221_A | Current L1 Socket 2 | sensor.py:1566 (A); wiki:330 meter2_currentL1 | high
3221_B | Current L2 Socket 2 | sensor.py:1576 (A); wiki:331 meter2_currentL2 | high
3221_C | Current L3 Socket 2 | sensor.py:1586 (A); wiki:332 meter2_currentL3 | high
3221_D | Current total Socket 2 | sensor.py:1596 (A); wiki:- | high
3221_E | Cos φ L1 Socket 2 | wiki:334 meter2_cosPhiL1 | high
3221_F | Cos φ L2 Socket 2 | wiki:335 meter2_cosPhiL2 | high
3221_10 | Cos φ L3 Socket 2 | wiki:336 meter2_cosPhiL3 | high
3221_11 | Cos φ Sum Socket 2 | wiki:337 meter2_cosPhiSum | high
3221_12 | Frequency Socket 2 | sensor.py:1468 (Hz); wiki:338 meter2_frequency | high
3221_13 | Smart Meter Real Power L1 (kW) | sensor.py:971 (kW); wiki:339 meter2_powerRealL1 | high
3221_14 | Smart Meter Real Power L2 (kW) | sensor.py:981; wiki:340 meter2_powerRealL2 | high
3221_15 | Smart Meter Real Power L3 (kW) | sensor.py:991; wiki:341 meter2_powerRealL3 | high
3221_16 | Active Power Total Socket 2 (kW per repo, W actual) | sensor.py:1486 (W); wiki:342 meter2_powerRealSum | high
3221_22 | Meter Reading Socket 2 (Wh) | sensor.py:1476 (kWh conv. sensor.py:2158); wiki:- | high
5221_3 | Smart Meter Voltage L1N | sensor.py:941 (V); wiki:363 meter4_voltageL1N | high
5221_4 | Smart Meter Voltage L2N | sensor.py:951 (V); wiki:364 meter4_voltageL2N | high
5221_5 | Smart Meter Voltage L3N | sensor.py:961 (V); wiki:365 meter4_voltageL3N | high
5221_6 | Smart Meter Voltage L1L2 | sensor.py:1011 (commented); wiki:366 meter4_voltageL1L2 | high
5221_7 | Smart Meter Voltage L2L3 | sensor.py:1021 (commented); wiki:367 meter4_voltageL2L3 | high
5221_8 | Smart Meter Voltage L3L1 | sensor.py:1031 (commented); wiki:368 meter4_voltageL3L1 | high
5221_9 | Smart Meter Current N | wiki:369 meter4_currentN | high
5221_A | Smart Meter Current L1 | sensor.py:1051 (A); wiki:370 meter4_currentL1 | high
5221_B | Smart Meter Current L2 | sensor.py:1061 (A); wiki:371 meter4_currentL2 | high
5221_C | Smart Meter Current L3 | sensor.py:1071 (A); wiki:372 meter4_currentL3 | high
5221_D | Smart Meter Current Total | sensor.py:1081 (A); wiki:- (no 5221_0D row) | high
5221_E | Cos φ L1 (meter4) | wiki:373 meter4_cosPhiL1 | high
5221_F | Cos φ L2 (meter4) | wiki:374 meter4_cosPhiL2 | high
5221_10 | Cos φ L3 (meter4) | wiki:375 meter4_cosPhiL3 | high
5221_11 | Cos φ Sum (meter4) | wiki:376 meter4_cosPhiSum | high
5221_12 | Frequency (meter4) | wiki:377 meter4_frequency | high
5221_13 | Active Power L1 (meter4) | wiki:378 meter4_powerRealL1 | high
5221_14 | Active Power L2 (meter4) | wiki:379 meter4_powerRealL2 | high
5221_15 | Active Power L3 (meter4) | wiki:380 meter4_powerRealL3 | high
5221_16 | Smart Meter Active Power Total | sensor.py:1041 (W); wiki:381 meter4_powerRealSum | high
4221_3 | meter3 Voltage L1N (central meter) | wiki:344 meter3_voltageL1N | medium
4221_4 | meter3 Voltage L2N | wiki:345 meter3_voltageL2N | medium
4221_5 | meter3 Voltage L3N | wiki:346 meter3_voltageL3N | medium
4221_6 | meter3 Voltage L1L2 | wiki:347 meter3_voltageL1L2 | medium
4221_7 | meter3 Voltage L2L3 | wiki:348 meter3_voltageL2L3 | medium
4221_8 | meter3 Voltage L3L1 | wiki:349 meter3_voltageL3L1 | medium
4221_9 | meter3 Current N | wiki:350 meter3_currentN | medium
4221_A | meter3 Current L1 | wiki:351 meter3_currentL1 | medium
4221_B | meter3 Current L2 | wiki:352 meter3_currentL2 (implied) | medium
4221_C | meter3 Current L3 | wiki:353 meter3_currentL3 (implied) | medium
4221_E | meter3 Cos φ L1 | wiki:354 meter3_cosPhiL1 (implied) | medium
4221_F | meter3 Cos φ L2 | wiki:355 meter3_cosPhiL2 (implied) | medium
4221_10 | meter3 Cos φ L3 | wiki:356 meter3_cosPhiL3 (implied) | medium
4221_11 | meter3 Cos φ Sum | wiki:357 meter3_cosPhiSum (implied) | medium
4221_12 | meter3 Frequency | wiki:358 meter3_frequency (implied) | medium
4221_13 | meter3 Active Power L1 | wiki:359 meter3_powerRealL1 (implied) | medium
4221_14 | meter3 Active Power L2 | wiki:360 meter3_powerRealL2 (implied) | medium
4221_15 | meter3 Active Power L3 | wiki:361 meter3_powerRealL3 (implied) | medium
4221_16 | meter3 Active Power Total | wiki:362 meter3_powerRealSum (implied) | medium

### States / sockets (states category; 2501_x socket 1 state block, 2502_x socket 2)
2501_1 | Main State Socket 1 | sensor.py:850 (MAIN_STATE_DICT); wiki:302 socket1_StateMain | high
2501_2 | Status Code Socket 1 | sensor.py:306 (STATUS_DICT); doc/alfen_props.md:163; wiki:304 socket1_StateLeds (HA treats _2 as the human status code) | high
2501_3 | Power State Socket 1 | sensor.py:842 (POWER_STATES_DICT); wiki:305 socket1_StateSocket | high
2501_4 | Mode3 State Socket 1 | sensor.py:826 (MODE_3_STAT_DICT); wiki:303 socket1_StateMode3 | high
2502_1 | Main State Socket 2 | sensor.py:1332 (MAIN_STATE_DICT); wiki:309 socket2_StateMain | high
2502_2 | Status Code Socket 2 | sensor.py:1339 (STATUS_DICT); wiki:310 socket2_StateLeds | high
2502_3 | Power State Socket 2 | sensor.py:1348 (POWER_STATES_DICT); wiki:311 socket2_StateSocket | high
2502_4 | Mode3 State Socket 2 | sensor.py:1356 (MODE_3_STAT_DICT); wiki:308 socket2_StateMode3 | high
2501_99 | display_Status socket 1 | wiki:306 display_Status | medium
2511_0 | Car CP Voltage High Socket 1 | sensor.py:762 (V); wiki:312 socket1_CP_PP_CPhigh | high
2511_1 | Car CP Voltage Low Socket 1 | sensor.py:772 (V); wiki:313 socket1_CP_PP_CPlow | high
2511_2 | Car PP resistance Socket 1 | sensor.py:782 (Ω); wiki:314 socket1_CP_PP_PP | high
2511_3 | Car PWM Duty Cycle Socket 1 | sensor.py:791 (%, raw/100); wiki:315 socket1_CP_PP_DC | high
2502_99 | display_Status socket 2 | wiki:307 display_Status | medium
2512_0 | Car CP Voltage High Socket 2 | sensor.py:1363 (V); wiki:316 socket2_CP_PP_CPhigh | high
2512_1 | Car CP Voltage Low Socket 2 | sensor.py:1373 (V); wiki:317 socket2_CP_PP_CPlow | high
2512_2 | Car PP resistance Socket 2 | sensor.py:1383 (Ω); wiki:318 socket2_CP_PP_PP | high
2512_3 | Car PWM Duty Cycle Socket 2 | sensor.py:1392 (%, raw/100); wiki:319 socket2_CP_PP_DC | high
2540_0 | Modbus TCP/IP Connection State | sensor.py:866 (MODBUS_CONNECTION_STATES_DICT); wiki:320 OD_modbusSlave1ConnectionState | high
2722_0 | CPO Name | sensor.py:834; wiki:231 OD_securityCpoName | high
2723_0 | Security profile | wiki:232 OD_securitySecurityProfile | medium
2723_1 | BackOffice authorization key | wiki:233 BackOfficeAuthorizationKey | medium
3600_1 | OCPP Boot notification State | sensor.py:858 (OCPP_BOOT_NOTIFICATION_STATUS_DICT); wiki:343 ocpp_bootNotificationState | high
3600_2 | OCPP Boot Last Time Send | sensor.py:1213 (epoch ms) | high
3600_3 | OCPP Boot Accept Time | sensor.py:1221 (epoch ms) | high
3600_6 | OCPP Heartbeat Last Received | sensor.py:1230 (commented out) | medium
3600_7 | OCPP Heartbeat Last Failed | sensor.py:1238 (epoch ms) | high
3600_8 | OCPP Heartbeat Last Sent | sensor.py:1247 (epoch ms) | high
3190_1 | Display State Socket 1 (user interface mode) | sensor.py:810 (STATUS_DICT, 28="See error Number"); wiki:321 OD_mainUserInterfaceMode1.state | high
3190_2 | Display Error Number Socket 1 | sensor.py:818 (DISPLAY_ERROR_DICT); wiki:- | high
3191_1 | Display State Socket 2 | sensor.py:1453; wiki:322 OD_mainUSerInterfaceMode2.state | high
3191_2 | Display Error Number Socket 2 | sensor.py:1461 | high

### Pricing / display (generic2)
3262_1 | Display Pricing currency | wiki:247 OD_dispDisplayPricing.currency | medium
3262_2 | Price Start Tariff (€) | number.py:309 (2 decimals); wiki:248 OD_dispDisplayPricing.startPrice | high
3262_3 | Price per kWh (€) | number.py:324; wiki:249 OD_dispDisplayPricing.energyPrice | high
3262_4 | Price per minute (€) | number.py:339; wiki:250 OD_dispDisplayPricing.minutePrice | high
3262_5 | Show disclaimer | wiki:251 OD_dispDisplayPricing.showDisclaimer | medium
3262_6 | Price other (€) | number.py:354 (-5..5); wiki:- | high
3262_7 | Price other description | text.py:63 | high

### SCN (Smart Charging Network)
2180_1 | SCN Network name | wiki:57 SCN_NetworkName | medium
2180_2 | SCN Socket ID | wiki:62 SCN_SocketId | medium
2180_3 | SCN Amount of sockets | wiki:63 SCN_NumberOfSockets | medium
2180_4 | SCN Alternating period (s) | wiki:61 SCN_AlternatingPeriod | medium
2180_5 | SCN Total current (A) | wiki:58 SCN_MaxStaticAvailableCurrent | medium
2180_6 | SCN Socket safe current (A) | wiki:59 SCN_UnconnectedSafeCurrent | medium
2180_7 | SCN Phase mapping 1 | wiki:64 SCN_PhaseMapping1 | medium
2180_8 | SCN Is unlocked | (myeve dict; not in wiki) | medium
2180_9 | SCN Phase mapping 2 | wiki:65 SCN_PhaseMapping2 | medium
2180_A | SCN Total safe current (A) | wiki:60 SCN_UnconnectedSafeCurrentTotal | medium

### MbusTCP (MbusTCP category)
2522_1 | MbusTCP1 enabled | wiki:69 MbusTCP1_enabled | medium
2522_2 | MbusTCP1 SlaveType | wiki:70 | medium
2522_3 | MbusTCP1 ConnectionType | wiki:71 | medium
2522_4 | MbusTCP1 IP address | wiki:72 | medium
2522_6 | MbusTCP1 Slave address | wiki:73 | medium
2523_2 | MbusTCP2 SlaveType | wiki:74 | medium
2523_4 | MbusTCP2 IP address | wiki:75 | medium
2523_6 | MbusTCP2 Slave address | wiki:76 | medium
2574_0 | Modbus smart meter config: word order | wiki:77 | medium
2574_1 | Modbus smart meter config: update time | wiki:78 | medium
2574_2 | Modbus smart meter config: read timeout | wiki:79 | medium
2574_3 | Modbus smart meter config: function code | wiki:80 | medium
2575_0 | Modbus smart meter UART baudrate | wiki:81 | medium
2575_1 | Modbus smart meter UART parity | wiki:82 | medium
2575_2 | Modbus smart meter UART address | wiki:83 | medium

### Misc
209F_0 | Mobile - actual RAT | wiki:280 OD_gprsActualRAT | medium
21A1_0 | Feature code | wiki:20 OD_sysFeatureCode | medium
21B2_0 | Service enabled | wiki:210 OD_sysServiceEnabled | medium
21B3_0 | Temp access expiration | wiki:211 OD_sysTempAccessExpiration | medium
21B4_0 | Is admin password default | wiki:212 OD_sysIsAdminPWDefault | medium
21B5_0 | Modem enabled | wiki:213 OD_sysModemEnabled | medium
21B6_0 | Operational time | wiki:214 OD_sysOperationalTime | medium
21B7_0 | Secure EEPROM | wiki:215 OD_sysSecureEEPROM | medium
21B8_0 | Aux board info | wiki:216 OD_auxBoardInfo | medium
204F_0 | Charging Station Configuration (not in this repo; from alfenctl context) | - | low
3258_0 | Minimum status duration | wiki:234 OD_minStatusDuration | medium
3272_0 | Certificate entries | wiki:219 OD_certificateEntries | medium
3273_0 | Rate units | wiki:220 OD_rateUnits | medium
3274_0 | Charging profile entries | wiki:221 OD_chargingProfileEntries | medium
3278_1 | Charging profile override socket 1 | wiki:222 OD_chargingProfileOverrides.socket1 | medium
3278_2 | Charging profile override socket 2 | wiki:223 OD_chargingProfileOverrides.socket2 | medium
5230_0 | Register meter value include phases | wiki:235 OD_registerMeterValueIncludePhases | medium
2400_1 | Master tag enabled | wiki:118 OD_masterTagVars.isEnabled | medium
2098_1..9 | Meter values sampled data 1-9 | wiki:162-170 | medium
2099_1..9 | Meter values aligned data 1-9 | wiki:171-179 | medium
209A_0 | Clock aligned data interval (s) | wiki:180 OD_commClockAlignedDataInterval | medium
2093_0 | Send station status | wiki:159 OD_commSendStationStatus | medium
2094_0 | Abort concurrent transaction | wiki:101 OD_commConcurrentTxAction | medium
2095_0 | Stop transaction on invalid tag | wiki:102 OD_commStopTransactionOnInvalidId | medium
2096_0 | Message attempts | wiki:160 OD_commTransactionMessageAttempts | medium
2097_0 | Message retry interval (s) | wiki:161 OD_commTransactionMessageRetryInterval | medium
209C_0 | Status notification method | wiki:181 OD_commStatusNotificationMethod | medium
209D_0 | Force heartbeats | wiki:182 OD_commForceHeartBeats | medium
20F4_0 | Network profile connection attempts | wiki:189 OD_commNetworkProfileConnectionAttempts | medium
2100_0 | Mobile APN name | wiki:190 OD_gprsAPNname | medium
2101_0 | Mobile APN user | wiki:191 OD_gprsAPNuser | medium
2102_0 | Mobile APN password | wiki:192 OD_gprsAPNpassword | medium
2103_0 | Mobile SIM PIN | wiki:193 OD_gprsSIMpin | medium
2118_0 | Modem manufacturer | wiki:199 OD_modemManufacturer | medium
2119_0 | Modem model | wiki:200 OD_modemModel | medium
2120_0 | Modem revision | wiki:201 OD_modemRevision | medium
2121_0 | Modem IMEI | wiki:202 OD_modemIMEI | medium
2124_0 | Informational status notifications | wiki:203 OD_commInformationalStatusNotifications | medium
2127_0 | Offline action NFC | wiki:105 OD_mainOfflineNFCAuthorization | medium
213C_0 | Online NFC action | wiki:110 OD_mainOnlineNFCAuthorization | medium
2171_0 | LED heart beat mode | wiki:243 OD_mainLEDHeartBeatMode | medium
2172_0 | LED heart beat intensity | wiki:244 OD_mainLEDHeartBeatIntensity | medium
2181_0 | RCD delay time | wiki:256 OD_mainRCDDelayTime | medium
2070_0 | RCD action immediate (6mA detect response) | wiki:257 OD_sysRCDActionImmediate | medium
2205_0 | Temperature log interval | wiki:261 OD_sensTemperatureLogInterval | medium
2206_0 | Accelerometer mode | wiki:262 OD_sensAccelerometerMode | medium
2210_0 | Accelerometer setpoint X | wiki:267 OD_sensAccelerometerSetpointX | medium
2213_0 | Accelerometer margin X | wiki:263 OD_sensAccelerometerMarginX | medium
2214_0 | Accelerometer margin Y | wiki:264 OD_sensAccelerometerMarginY | medium
2215_0 | Accelerometer margin Z | wiki:265 OD_sensAccelerometerMarginZ | medium
2216_0 | Accelerometer log interval | wiki:266 OD_sensAccelerometerLogInterval | medium
2250_0 | Tamper sensor | wiki:268 OD_sensTamper | medium
21B0_0 | PE DET enabled | wiki:269 OD_sysPEDETEnabled | medium
2072_1 | Mobile DHCP Address | sensor.py:607 (commented out) | medium
2072_2 | Mobile Fixed DHCP | (myeve dict) | medium
2075_2 | Mobile Fixed IP address | (myeve dict; wiki:134 OD_commIPaddress1_isFixed) | medium
2079_2 | Mobile Fixed DNS 1 | (myeve dict) | medium
207A_1 | Ethernet DHCP Address | sensor.py:682 (commented) | medium
207A_2 | Ethernet Fixed DHCP | (myeve dict) | medium
207D_2 | Ethernet Fixed IP address | wiki:141 OD_commIPaddress2_isFixed | medium
207E_2 | Ethernet Fixed DNS 1 | (myeve dict) | medium
207F_2 | Ethernet Fixed DNS 2 | (myeve dict) | medium
2080_2 | Mobile Fixed DNS 2 | (myeve dict) | medium
2081_0 | BO Protocol Name | (myeve dict) | medium
2085_0 | Charge point serial number | (myeve/EDS context) | low
208A_0 | Ping pong interval (s) | wiki:151 OD_commPingPongInterval | medium
208B_1 | Wired websocket timeout (s) | wiki:152 OD_commWebSocketTimeout wired | medium
208B_2 | GPRS websocket timeout (s) | wiki:153 | medium
208F_0 | Central metering interval | wiki:158 OD_commCentralMeteringInterval | medium
2088_0 | Meter value transmission mode | wiki:149 | medium
2089_0 | Meter value alignment | wiki:150 | medium
2188_0 | DPSG Giro-e method status | wiki:116 OD_mainDPSGiroeMethodStatus | medium
2065_1 | Smart Charging Mode Enabled | (myeve dict) | medium
2066_0 | Active LB Status Flags | (myeve dict) | medium
206B_1 | Nuvve Support Active | wiki:126 OD_sysNuvveSupport.active | medium
206B_2 | Nuvve Support Interval (s) | wiki:127 | medium
206B_3 | Nuvve Support Threshold (W) | wiki:128 | medium
206C_1 | OCPP 1.5 Smart Charging type | wiki:129 OD_sysOCPP15SmartCharging_smartChargingType | medium
2071_1 | Ethernet Back Office URL domain:port | wiki:130 OD_commBackOfficeURLwired_serverDomainAndPort | medium
2071_2 | Ethernet Back Office URL path | wiki:131 | medium
2078_1 | Mobile Back Office URL domain:port | wiki:136 OD_commBackOfficeURL_serverDomainAndPort | medium
2078_2 | Mobile Back Office URL path | wiki:137 | medium
20F0_1 | Network Profile 1 BO Version | wiki:183 OD_comNetworkProfile1.boVersion | medium
20F0_3 | Network Profile 1 CSMS URL | wiki:184 | medium
20F0_4 | Network Profile 1 message timeout | wiki:185 | medium
20F0_5 | Network Profile 1 security profile | wiki:186 | medium
20F0_6 | Network Profile 1 BO interface | wiki:187 | medium
2140_0 | NFC Reader Tag Delay (s) | (myeve dict) | medium
2138_0 | NFC Reader Type | (myeve dict) | medium
2139_0 | NFC Scan Interval (s) | (myeve dict) | medium
213A_0 | NFC Reader Model | (myeve dict) | medium
213E_0 | Offline action Local list | (myeve dict) | medium
2153_0 | Max time to open S2 (s) | (myeve dict) | medium
215F_0 | External Max Current (station) | (myeve dict) | medium
2131_0 | Start up delay (s) | (myeve dict) | medium
2132_0 | Switch error delay (s) | (myeve dict) | medium
2133_0 | Current error delay (s) | (myeve dict) | medium
2134_0 | High frequency error delay (s) | (myeve dict) | medium
212E_1 | P1 read status | (myeve dict) | medium
212E_2 | P1 version | (myeve dict) | medium
212E_3 | P1 timestamp | (myeve dict) | medium
2165_1 | DSC 0 Status | (myeve dict) | medium
2165_2 | DSC 0 Safe current (A) | (myeve dict) | medium
2165_3 | DSC 0 Max current (A) | (myeve dict) | medium
2165_4 | DSC 0 Valid to | (myeve dict) | medium
2166_1..4 | DSC 1 Status/SafeCurrent/MaxCurrent/ValidTo | (myeve dict) | medium
2167_1..4 | DSC 2 Status/SafeCurrent/MaxCurrent/ValidTo | (myeve dict) | medium
2175_0 | External Modbus support | (myeve dict) | medium
2176_0 | Device ID | (myeve dict) | medium
2177_0 | QR URL Socket 1 | (myeve dict) | medium
2178_0 | QR URL Socket 2 | (myeve dict) | medium
2179_0 | Dynamic QR code enabled | (myeve dict) | medium
2183_0 | Cover lock enabled | wiki:245 OD_mainCoverLockEnabled | medium
3261_0 | Display items enabled | wiki:246 disp_itemsEnabled | medium

## Enum maps (value → label)

### 2501_2 / 2502_2 Status (STATUS_DICT) — sensor.py:56-102
0=Unknown, 1=Off, 2=Booting, 3=Check Mains, 4=Available, 5=Authorizing, 6=Authorized, 7=Cable connected, 8=EV Connected, 9=Preparing Charging, 10=Wait Vehicle Charging, 11=Charging Normal, 12=Charging Simplified, 13=Suspended Over-Current, 14=Suspended HF Switching, 15=Suspended EV Disconnected, 16=Finish Wait Vehicle, 17=Finish Wait Disconnect, 18=Error Protective Earth, 19=Error Power Failure, 20=Error Contactor Fault, 21=Error Charging, 22=Error Power Failure, 23=Error Temperature, 24=Error Illegal CP Value, 25=Error Illegal PP Value, 26=Error Too Many Restarts, 27=Error, 28=Error Message, 29=Error Message Not Authorised, 30=Error Message Cable Not Supported, 31=Error Message S2 Not Opened, 32=Error Message Time-Out, 33=Reserved, 34=In Operative, 35=Load Balancing Limited, 36=Load Balancing Forced Off, 38=Not Charging, 39=Solar Charging Wait, 40=Charging Non Charging, 41=Solar Charging, 42=Charge Point Ready, Waiting For Power, 43=Partial Solar Charging

### 2501_1 / 2502_1 Main State (MAIN_STATE_DICT) — sensor.py:148-206
-1=Illegal, 0=Unknown, 1=Booting, 2=Available, 3=Cable Connected, 4=Cable Connected Timeout, 5=EV Connected, 6=Button Activated, 7=NFC Available, 8=NFC Authorised, 9=Wait for EV Connect, 10=Charging Test Relays, 11=Charging Power Off, 12=Charging Power Off Low Max Current, 13=Charging Power Starting, 14=Charging Power On, 15=Charging Power On Simplified, 16=Charging Wait for EV Reconnect, 17=Charging Terminating, 18=Charging Wakeup, 19=Wait for Disconnect, 20=Wait for Release Authorisation, 21=Charging Recover from Outage, 22=Error, 23=Error Message, 24=Error Message Cable not Supported, 25=Error Illegal Mode 3, 26=Error Too Many Restarts, 27=Error Charging, 28=Error Charging Overcurrent, 29=Error Charging HF Contactor Switching, 30=Error S2 Not Opened, 31=Error Protective Earth, 32=Error Relays, 33=Error Low Supply Voltage, 34=Error Internal Voltage, 35=Error Powermeter, 36=Error Temperature, 37=Suspended, 38=Inoperative, 39=Reserved, 40=Error Charging RCD Signaled, 41=Charging Power Off Ventilating, 42=Charging Power Off Suspended, 43=Charging Power Off Phase Change, 44=Wait for Start Metervalue, 45=Wait for Stop Metervalue, 46=Error Socket Motor, 47=Cable Conencted Type E, 48=Cable Connected Time out Type E, 49=Charging Type E, 50=Wait for Disconnect Type E, 51=Charging Suspended Type E, 52=Charging Low Max Current Type E, 53=Invalid Card, 54=EV Connected Unauthorized, 55=Wait for Disconnect PP

### 2501_3 / 2502_3 Power State (POWER_STATES_DICT) — sensor.py:126-145
0=Normal Operation, 1=Inactive, 2=Connected ISO15118, 3=Wait for EV Connect, 4=EV Connected, 5=Active, 6=Wait for S2 Close, 7=Wait for S2 Open, 8=Suspended, 9=Ventilating, 10=Wakeup State E, 11=Wakeup State B1, 12=Error, 13=Error EV Detect, 14=Wait for EV Disconnect, 15=Prepared, 16=Connected ISO15118 Error, 17=Count

### 2501_4 / 2502_4 Mode 3 State (MODE_3_STAT_DICT) — sensor.py:119-124
160=STATE_A, 161=STATE_A1, 162=STATE_A1, 177=STATE_B1, 178=STATE_B2, 193=STATE_C1, 194=STATE_C2, 209=STATE_D1, 210=STATE_D2, 224=STATE_E, 240=STATE_F
(raw values are ASCII: 0xA0..0xF0)

### 3190_1/3191_1 Display State — STATUS_DICT (same map as 2501_2; value 28 → "See error Number") — sensor.py:2148-2152

### 3190_2/3191_2 Display Error (DISPLAY_ERROR_DICT) — sensor.py:104-118
0=No Error, 1=Not able to charge. Please call for support., 2=Charging not started yet, to continue please reconnect cable, 3=Too many retries. Please check your charging cable, 4/5/6=One moment please... Your charging session will resume shortly., 7=S2 not open. Please reconnect cable., 101=Error in installation. Please check installation, 102/104/105/106=Not able to charge. Please call for support., 103=Input voltage too low, not able to charge., 108/109=Not displayed, 201/212=Error in installation. Please check installation or call for support., 202=Input voltage too low, not able to charge. Please call your installer., 203=Inside temperature high. Charging will resume shortly., 204=Temporary set to unavailable., 206=Temporary set to unavailable. Contact CPO or try again later., 208-210=Not displayed, 211=Not able to lock cable. Please call for support., 213=Not displayed, 301/302/303=One moment please your charging session will resume shortly., 304=Charging not started yet to continue please reconnect cable., 401=Inside temperature high. Charging will resume shortly., 402=Inside temperature low. Charging will resume shortly., 404=Not able to lock cable. Please reconnect cable., 405=Cable not supported. Please try connecting your cable again., 406=No communication with vehicle. Please check your charging cable., 407=Not displayed

### 3600_1 OCPP Boot notification state — sensor.py:208-214
0=Not Sent, 1=Awaiting Reply, 2=Rejected, 3=Accepted, 4=Pending

### 2540_0 Modbus TCP connection state — sensor.py:216-222
0=Idle, 1=Initializing, 2=Normal, 3=Warning, 4=Error

### 3293_0 WiFi status — sensor.py:224-229
0=Not Initialized, 1=Not Configured, 2=Not Connected, 3=Connected

### Select enums (write; value → option as used by HA)
- 3280_1 CHARGING_MODE_DICT (select.py:29): Disable=0, Comfort=1, Green=2
- 2069_0 PHASE_ROTATION_DICT (select.py:30-39): strings L1, L2, L3, L1L2L3, L1L3L2, L2L1L3, L2L3L1, L3L1L2, L3L2L1 (input "L1,L2,L3" style)
- 2126_0 AUTH_MODE_DICT (select.py:41): Plug and Charge=0, RFID=2
- 5217_0 LOAD_BALANCE_PROTOCOL_DICT (select.py:43-47): Energy Management System=-1, Modbus TCP/IP=4, DSMR4.x/SMR5.0 (P1)=5
- 206F_0 LOAD_BALANCE_RECEIVED_MEASUREMENTS_DICT (select.py:49-52): Exclude Charging Ev=0, Include Charging Ev=1
- 205D_0 DISPLAY_LANGUAGE_DICT (select.py:54-73): locale strings (ca_ES, hr_HR, cz_CZ, da_DK, nl_NL, en_GB, fi_FI, fr_FR, de_DE, hu_HU, is_IS, it_IT, lv_LV, no_NO, pl_PL, pt_PT, ro_RO, sk_SK, es_ES, sv_SE)
- 20F0_E / 20F1_E PRIORITIES_DICT (select.py:75): Disable=0, 1=1, 2=2, 3=3, 4=4
- 205F_0 OPERATIVE_MODE_DICT (select.py:77-80): Operative=0, In-operative=2
- 2113_0 GPRS_NETWORK_MODE_DICT (select.py:82): Automatic=0, Manual=1
- 2114_0 GPRS_TECHNOLOGY_DICT (select.py:84-88): 2G (GPRS)=0, 3G (UMTS)=1, 4G (LTE)=2
- 2191_1 DSMR_SMR_INTERFACE_DICT (select.py:113-117): Serial=0, Telnet=1, HomeWizard Wi-Fi P1=2
- 2530_1 LOAD_BALANCE_DATA_SOURCE_DICT (select.py:102-106): Meter=0, Meter + EMS Monitoring=1, Energy Management System=3
- 2189_0 ALLOWED_PHASE_DICT (select.py:91-94): 1 Phase=1, 3 Phases=3
- 216C_0 DIRECT_EXTERNAL_SUSPEND_SIGNAL (select.py:108-112): Not allowed=0, Allowed suspend when closed=1, Allowed suspend when open=2
- 2125_0 / 3125_0 SOCKET_TYPE_DICT (select.py:119-127): Fixed Cable Unknown=0, Mennekes=1, FCT=2, Schuko=3, FIXED_CABLE_TYPE_1=4, FIXED_CABLE_TYPE_2=5, UNKNOWN=99
- 2137_0 CAR_DISCONNECT_ACTION_DICT (select.py:129-134): Continue=0, Abort Lock=1, Abort Unlock=2, Abort Unlock When Offline=3
- 328C_0 WIFI_SECURITY_MODE_DICT (select.py:136-147): WPA PSK TKIP=2097154, WPA PSK AES=2097156, WPA PSK AES&TKIP=2097158, WPA2 PSK AES=4194308, WPA3 PSK AES=16777220, WPA2 PSK TKIP=4194306, WPA2 PSK AES&TKIP=4194310, WPA2 WPA PSK AES=6291460, WPA2 WPA PSK AES&TKIP=6291462, WPA3 WPA2 PSK AES=21233668

### License bitmap (21A2_0) — const.py:172-184
None=0, LoadBalancing_SCN=1, LoadBalancing_Static=2, LoadBalancing_Active=4, HighPowerSockets=16, RFIDReader=256, PersonalizedDisplay=4096, Mobile3G4G=65536, Payment_QRCode=131072, Payment_GiroE=1048576, Expose_SmartMeterData=16777216, ObjectID=2147483648

## Units
- A (ampere): 2062_0, 2067_0, 2068_0, 206A_0, 2128_0, 2129_0, 3129_0, 212A_0, 312A_0, 212B_0, 312B_0, 212C_0, 312C_0, 212D_0, 312D_0, 212F_1..3, 2160_0, 3160_0, 2161_0, 2173_0, 3173_0, 2174_0, 2180_5, 2180_6, 2180_A, 2221_9..D, 3221_9..D, 5221_9..D
- V (volt): 2221_3..8, 3221_3..8, 5221_3..8, 2511_0, 2511_1, 2512_0, 2512_1
- W (watt): 2221_16, 3221_16, 5221_16, 3280_3 (comfort level)
- kW: 3221_13..15 per repo entity labels (wiki says sub 19-22 are kW); note 2221_13..15 labeled kW in wiki "Active Power L1/L2/L3 (kW)"
- Hz: 2221_12, 3221_12, 5221_12
- kWh: 2221_22, 3221_22 (raw Wh, /1000 for kWh — conversion sensor.py:2158)
- %: 2061_2, 3280_2, 2511_3, 2512_3 (PWM duty cycle raw/100)
- °C: 2201_0, 2249_0, 2249_1, 2203_0, 2204_0
- Ω (ohm): 2511_2, 2512_2
- s (seconds): 2086_0, 208D_1/2, 208E_1/2, 2135_0, 2136_0, 2168_0, 2169_0, 2184_0, 21B9_0, 2180_4
- EUR: 3262_2, 3262_3, 3262_4, 3262_6
- dB (signal strength): 2110_0, 2111_0
- minutes: 2060_0 (raw ms, /1000), 206E_0 (timezone), 2059_0 (sensor computes minutes since sync)

## Multi-sub objects (full sub-index layout)

### 2221_x meter1 (socket 1 meter) — cat "meter1" — wiki lines 287-305
sub 3=voltage L1N (V), 4=voltage L2N, 5=voltage L3N, 6=voltage L1L2, 7=voltage L2L3, 8=voltage L3L1, 9=current N (A), A(10)=current L1, B(11)=current L2, C(12)=current L3, E(14)=cosφ L1, F(15)=cosφ L2, 10(16)=cosφ L3, 11(17)=cosφ sum, 12(18)=frequency (Hz), 13(19)=active power L1, 14(20)=active power L2, 15(21)=active power L3, 16(22)=active power total, 22(34)=meter reading (energy delivered total, Wh)
NOTE: wiki "Sub ID" summary section (raw wiki lines 390-436) lists voltage=3..8, current=9..12, cosφ=14-17, frequency=18, power=19-22 as DECIMAL values, while the id table uses hex subIds. hex 0x13=19 matches "Active Power L1". The ids are consistent when the wiki summary's decimal numbers are interpreted as hex. Alfen returns 2221_22 meter reading in Wh (HA divides by 1000 for kWh).

### 3221_x meter2 (socket 2 meter / dual-socket) — wiki lines 329-348 (wiki has a duplicate 3221_0C row)
Same layout as 2221_x (voltage 3-8, current 9-C, cosφ E-11, frequency 12, power 13-16, meter reading 22). HA maps 3221_13..16 to Smart Meter Real Power (kW).

### 4221_x meter3 (central/optional energy meter 3) — wiki lines 350-368: identical layout.

### 5221_x meter4 (smart meter / external metering) — wiki lines 369-387: identical layout.

### 2501_x socket 1 state block (cat "states") — wiki lines 302-312
sub 1=StateMain, 2=StateLeds (HA: Status), 3=StateSocket (HA: Power State), 4=StateMode3, 0x99=display_Status
### 2502_x socket 2 state block — wiki lines 313-317: same layout (1=StateMain, 2=StateLeds, 3=StateSocket, 4=StateMode3, 99=display_Status)
### 2511_x socket 1 CP/PP block — wiki lines 318-321: sub 0=CP high (V), 1=CP low (V), 2=PP resistance (Ω), 3=PWM duty cycle (%)
### 2512_x socket 2 CP/PP block — wiki lines 322-325: same layout.
### 2098_x sampled data config: sub 1..9 = SampledData_1..9 (wiki:162-170)
### 2099_x aligned data config: sub 1..9 = AlignedData_1..9 (wiki:171-179)
### 2180_x SCN block (wiki lines 57-66 raw; artifact offset applied): sub 1=NetworkName, 2=SocketId, 3=NumberOfSockets, 4=AlternatingPeriod, 5=MaxStaticAvailableCurrent, 6=UnconnectedSafeCurrent, 7=PhaseMapping1, 8=IsUnlocked (myeve dict; not in wiki), 9=PhaseMapping2, A=UnconnectedSafeCurrentTotal
### 2522_x MbusTCP1: sub 1=enabled, 2=SlaveType, 3=ConnectionType, 4=IPaddress, 6=SlaveAddress (wiki:69-73); 2523_x MbusTCP2 same (wiki:74-76)
### 2574_x ModbusSmartMeterConfig: sub 0=wordOrder, 1=updateTime, 2=readTimeout, 3=functionCode (wiki:77-80)
### 2575_x ModbusSmartMeterUart: sub 0=baudrate, 1=parity, 2=address (wiki:81-83)
### 20F0_x Network profile 1: sub 1=boVersion, 3=csmsUrl, 4=messageTimeout, 5=securityProfile, 6=boInterface, E(14)=priority (wiki:183-188); 20F1_x profile 2 same layout; 20F2_x profile 3; 20F3_x profile 4
### 2165_x / 2166_x / 2167_x DSC (dynamic setpoint control): sub 1=Status, 2=SafeCurrent, 3=MaxCurrent, 4=ValidTo (myeve dict)

## Type hints (from doc/alfen_props.md sample response lines 62-150)
GET /api/prop?ids= returns per-property: {id, access, type, len, cat, value}. Observed types: 7 (int, e.g. 2056_0), 8 (real/float, e.g. 2221_3, 2201_0), 27 (large int/bytearray, e.g. 2060_0 uptime). access=1 observed (readable; the integration also writes most of these successfully via POST).
Read-only (never written by HA): all meter values (2221_x, 3221_x, 4221_x, 5221_x), 2501_x/2502_x states, 2511_x/2512_x CP/PP, 3600_x, 2540_0, 3190_x/3191_x, 2201_0, 2249_x, 2056_0, 2057_0, 2060_0, 2187_0, 2059_0, 2104_0, 2105_0, 2110_0, 2112_0, 2052_1, 2005_0, 2050_0, 2051_0, 2054_0, 1008_0, 1009_0, 100A_0, 3182_0, 21A2_0, 205E_0, 212F_1..3, 2128_0, 212B_0, 212C_0, 212D_0, 2160_0, 3160_0, 2161_0, 2722_0, 328D_0, 3293_0, IP/netmask/DNS address sensors.
Writable (proven by HA set_value/switch/number/select/text services): 2129_0, 3129_0, 2126_0, 2069_0, 2185_0, 3280_1..5, 2061_1, 2061_2, 2068_0, 2062_0, 2067_0, 206A_0, 206E_0, 2076_0, 2086_0, 208D_1/2, 208E_1/2, 209B_0, 2113_0, 2114_0, 2115_0, 2116_0/1, 2117_0, 2125_0, 3125_0, 212A_0, 2136_0, 2137_0, 213B_0, 213D_0, 215E_0, 2168_0, 2169_0, 2174_0, 2184_0, 2189_0, 216C_0, 2191_1, 21B9_0, 2530_1, 5217_0, 3262_2..4, 3262_6, 3262_7, 3284_0, 328A_0, 328B_0, 3291_0, 3292_0, 20F0_E, 20F1_E, 205D_0, 205F_0, 2063_0.

## API mechanics (alfen.py)
- Base URL https://<host>/api/{login,logout,info,prop,cmd,log,transactions,chargingprofiles} (alfen.py:1510, README, doc/alfen_props.md)
- Login POST {username, password, displayname}; connection-based auth; wallbox allows single session (README)
- Read: GET /api/prop?cat=<category>&offset=<N> paginated by `total`/len (alfen.py:1002-1050) or GET /api/prop?ids=<comma list> (doc/alfen_props.md:59)
- Write: POST /api/prop body {"2129_0": {"id": "2129_0", "value": 16}} (alfen.py:938-941, doc/alfen_props.md:46-52). Values sent as str(value) in _update_value (alfen.py:941: json={api_param: {ID: api_param, VALUE: str(value)}})
- Categories (const.py:60-76): comm, display, generic, generic2, MbusTCP, meter1, meter2, meter4, ocpp, states, temp, transactions, logs. NOTE: meter3/4221_x is in cat "meter3" (not in the default fetch list; meter4 = 5221_x fetched via cat "meter4").
- Commands POST /api/cmd {"command":"reboot"} or "txerase" (alfen.py:1107-1113)
