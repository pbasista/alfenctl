FULL FINDINGS (windows-findings) =====================================================

How these were obtained (extraction, decompilation, decryption, mining loop):
`windows-guide.md` in this directory. Reproduction steps below are abbreviated.

Decoding rules (critical):
1. C# first arg of GetProperty/HasProperty/Add* = propId in DECIMAL which equals the hex id (8273=0x2051 → 2051_00); 2nd arg = subId decimal (TT keys use hex: sub 10 dec = _0A).
2. Packed uint keys in AddCustomSelect/AddPlainPassword/UpdateProperties = (propId<<8)|subId: 2127616=0x207700→2077_00; 2116865=0x204D01→204D_01; 2195457=0x218001→2180_01; 2204160=0x21A200→21A2_00.
3. REST /prop JSON per property: id='PPPP_SS', value, type (SDT code), access (1=read-only), cat (category), len. Categories: generic, generic2, ocpp, comm, scn, meter1..meter4, MbusTCP, states, temp, accelero, leds, display. (ICULanDevice.cs:1835-1888 ParseProperty; LogHttpClientHandler.cs:36 polls 2059_0,2060_0,2191_2,2191_3,2210_0,2211_0,2212_0 constantly)
4. SDT codes (SDT.cs): 0x0005=UNSIGNED8(bool), 0x0002=INTEGER16, 0x0003=int16, 0x0004=INT32, 0x0006=UINT16, 0x0007=UINT32, 0x0008=REAL32, 0x0009=VISIBLE_STRING, 0x000F=OCTET/BYTEARRAY, 0x001B=TIME_OF_DAY(ms epoch), 64=BYTEARRAY, 65=ARRAY_16.
5. EDS.xml Id='PPPPsubNN' suffix parsed as hex by EDSParser.cs:29-38 but is decimal in some entries (2221sub10=Frequency vs TT 2221_12); TT + code semantics win.

MASTER TABLE <id> | <name/title> | <evidence> | <confidence>
--- Identity/general ---
1008_00 | OD_manufacturerDeviceName Platform type | TT:2 EDS:3 | high
1009_00 | HW version per node (1=comm unit,3=master socket,4=slave) | EDS:9 | high
100A_00 | OD_manufacturerSoftwareVersion firmware version controller board | TT:3 EDS:35 DlgUpload.cs:180 | high
2005_00 | ODversion Object Dictionary Version | EDS:61 | high
204D_01 | sysModuleHardwareRevision HW version controller board (EBoardRevision) | TT:20 PanelInformation.cs:312 | high
204D_02 | controller board assembly (EBoardAssy) | PanelInformation.cs:312 | high
204D_03 | HW version power board | TT:21 PanelInformation.cs:318 | high
204D_04 | power board assembly | PanelInformation.cs:318 | high
204F_00 | OD_sysChargePointConfiguration Charge point configuration bitmask: bits0-1 phases (0=1F,2=3F); 0x30 cable (0/16/32=FCT1/2/3, 48=Socket); 0x80=Type-E 2nd outlet | PanelSockets.cs:43-45; PanelPower.cs:266,288; CFG:21 ID_204F | high
2050_00 | sysChargePointModel Model (Twin 3.0,EVe-dual,EVe-single,Compact,LOLO3,ICU Eve Mini,TUBE,Twin 4.0) | TT:4 EDS:67-95 PanelInformation.cs:300 | high
2051_00 | sysChargePointSerialNumber Object Number/serial; license purchase ID; write guarded by AllowObjectIDUpdate | TT:5 EDS:97 ICULanDevice.cs:1869,1964 PanelInformation.cs:629 | high
2052_01 | sysBoardSerial:Value Ethernet MAC address | TT:123 EDS:109 PanelConnectivity.cs:503 | high
2052_02 | sysBoardSerial:isFixed Fixed Ethernet MAC | EDS:115 | high
2053_00 | sysChargeBoxIdentity Customer Ident. number | TT:6 EDS:121 MainWindow.cs:1518 | high
2054_00 | sysFirmwareVersion NFC reader SW version ('#N:' splits HW/SW) | EDS:127 ICULanDevice.cs:2685-2705 | medium
2055_00 | sysChargePointVendor vendor 'Alfen BV' | TT:13 PanelInformation.cs:303 | high
2056_00 | sysBootCount Number of bootups | TT:294 EDS:139 PanelMonitoring.cs:248 | high
2057_00 | sysBootReason Boot Reason | EDS:142 | high
2059_00 | sysDateTime Charger date and time (ms epoch) | TT:14 EDS:145 ICULanDevice.cs:2604 | high
205A_00 | sysTimeZone Time zone hours (legacy) | EDS:151 PanelInformation.cs:88,445 | high
205B_00 | sysDaylightSavings 0=None 1=EU 2=USA 3=Australia | TT:15 EDS:159-187 | high
205C_01 | sysPosition:latitude Latitude | TT:16 EDS:189 PanelInformation.cs:448 | high
205C_02 | sysPosition:longitude Longitude | TT:17 EDS:196 PanelInformation.cs:449 | high
205D_00 | sysLanguage Display Language ('nl_NL','en_GB') | TT Interface PanelInterface.cs:115 ICUBackOffice.cs:493 | high
205E_00 | numberOfSockets (1 or 2) | LANConnection.cs:230 | medium
205F_00 | sysStatusFlags socket status bitmask bit1=sock1 inop bit2=sock2 inop | PanelMonitoring.cs:526-531,702-706 | high
205F_03 | Status left socket 0=Operative 1=In-operative | TT:298 PanelMonitoring.cs:260 | high
205F_05 | Status right socket | TT:299 PanelMonitoring.cs:306 | high
2060_00 | sysUpTime System uptime (s) | TT:295 PanelMonitoring.cs:247 | high
2061_01 | sysIntensity:auto Auto dim flags bit1=Time bit2=Inactivity bit4=QR (single bool if len<7) | TT PanelInterface.cs:98-109 | high
2061_02 | sysIntensity:intensity Led/Display light intensity % | TT EDS:257 PanelInterface.cs:111 | high
2062_00 | sysMaxStationCurrent Station maximum current (A) | TT:25 EDS:263 PanelPower.cs:213 | high
2063_00 | sysPlugAndChargeIdentifier Plug & charge ID | TT:95 EDS:270 PanelAuthorization.cs:313 | high
2064_00 | sysLoadBalancingMode 0=off 1=Static 2=Active 3=both (TT shows 2064_01 Static / 2064_02 Active checkboxes) | TT:49-50 EDS:276-304 PanelLoadbalancing.cs:605,640 | high
2066_00 | sysStatusFlags System Status u32 bitmask | EDS:306 | medium
2067_00 | sysMaxSmartMeterCurrent Maximum smart meter current (A) | TT:51 EDS:312 PanelLoadbalancing.cs:683 | high
2068_00 | sysActiveSafeCurrent Active LB safe current (A) | TT:52 EDS:319 PanelLoadbalancing.cs:687 | high
2069_00 | sysP1PhaseConnection Phase rotation L1/L2/L3/L1L2L3/L1L3L2/L2L1L3/L2L3L1/L3L1L2/L3L2L1 | TT:53 EDS:326 PanelLoadbalancing.cs:692 | high
206A_00 | sysMinimumChameleonCurrent Chameleon min current (A) | TT:26 PanelPower.cs:304 | high
206B_01 | sysNuvveSupport:active Nuvve Enabled | TT:124 PanelConnectivity.cs:658(8299,1) | high
206B_02 | sysNuvveSupport:interval Interval (s) | TT:125 PanelConnectivity.cs:659 | high
206B_03 | sysNuvveSupport:threshold Threshold (W) | TT:126 PanelConnectivity.cs:660 | high
206C_01 | sysOCPP15SmartCharging:smartChargingType 0=None 1=GreenFlux 2=Enervalis 3=Cohere 4=EVNet 5=OCPP16OCPP | TT:127 EDS:329 PanelConnectivity.cs:651(8300,1) | high
206C_02 | SC minimum charging time (s) | EDS:350 | high
206C_03 | SC check time (s) | EDS:354 | high
206C_04 | SC default measurement interval (s) | EDS:358 | high
206C_05 | SC minimum measurement interval (s) | EDS:362 | high
206C_06 | SC maximum measurement interval (s) | EDS:366 | high
206C_07 | SC measurement per phase 0=No | EDS:370 | high
206E_00 | sysTimeZoneMinutes Time zone (min offset UTC) | TT:18 EDS:385 PanelInformation.cs:441 | high
206F_00 | sysSmartMeterIncludesEV Received Measurements 0=Exclude charging EV 1=Include | TT:86 EDS:393 PanelLoadbalancing.cs:653(8303) | high
2070_00 | sysRcdActionImmediate 6mA Detect Response 0=Smart 1=Immediate | TT:279 EDS:496 PanelAlerts.cs:86(8304) | high
2071_01 | commBackOfficeURLwired:ServerDomainAndPort Back office URL wired | TT:128 EDS:514 PanelConnectivity.cs:491(8305,1) | high
2071_02 | commBackOfficeURLwired:ServerPath Back office path wired | TT:129 PanelConnectivity.cs:492 | high
2073_01 | commNetMask1:Value Netmask (mobile) | TT:130 PanelConnectivity.cs:519(8307,1) | high
2074_01 | commGWaddress1:Value Gateway (mobile) | TT:131 PanelConnectivity.cs:520(8308,1) | high
2075_01 | commIPaddress1:Value IP Address (mobile) | TT:133 PanelConnectivity.cs:518 | high
2075_02 | commIPaddress1:isFixed Fixed IP (mobile) | TT:132 PanelConnectivity.cs:516(8309,2) | high
2076_00 | commBackOfficeShortName Backoffice preset (CSV 'bopreset,meterName') | TT:121 EDS:460 PanelConnectivity.cs:418-420 PanelLoadbalancing.cs:584-588 | high
2077_00 | commConnectMethod 0=None 1=Wired 2=Mobile 3=Auto (device may report 99) | TT:122 EDS:466 PanelConnectivity.cs:448-452 PanelMonitoring.cs:172(8311) | high
2078_01 | commBackOfficeURL:ServerDomainAndPort Back office URL mobile | TT:134 EDS:526 PanelConnectivity.cs:508(8312,1) | high
2078_02 | commBackOfficeURL:ServerPath mobile | TT:135 PanelConnectivity.cs:509 | high
2079_01 | commDNS1_1:Value DNS 1 mobile | TT:136 EDS:544 PanelConnectivity.cs:521(8313,1) | high
207B_01 | commNetMask2:Value Netmask 2 wired | TT:137 EDS:570 PanelConnectivity.cs:515(8315,1) | high
207C_01 | commGWaddress2:Value Gateway 2 wired | TT:138 PanelConnectivity.cs:516(8316,1) | high
207D_01 | commIPaddress2:Value Wired IP | TT:140 EDS:602 PanelConnectivity.cs:498(8317,1) ICULanDevice.cs:147 | high
207D_02 | commIPaddress2:isFixed Fixed IP wired | TT:139 PanelConnectivity.cs:496(8317,2) | high
207E_01 | commDNS2_1:Value DNS2 1 wired | TT:141 PanelConnectivity.cs:501(8318,1) | high
207F_01 | commDNS2_2:Value DNS2 2 wired fallback | TT:142 PanelConnectivity.cs:502(8319,1) | high
2080_01 | commDNS2:Value DNS 2 mobile fallback | TT:143 EDS:659 PanelConnectivity.cs:522(8320,1) | high
2081_00 | commProtocolName 'ocpp/json' | EDS:672 CFG:41 | high
2082_00 | commProtocolVersion 1.5/1.6/2.0.1 | TT:144 EDS:678 PanelConnectivity.cs:482(8322) | high
2083_00 | commListenerIPaddress Listener IP | EDS:684 | medium
2084_00 | commListenerPort Listener port | EDS:690 | medium
2085_00 | commDefaultHeartBeatInterval default heartbeat | EDS:696 | medium
2086_00 | commActualHeartBeatInterval Actual heartbeat interval (s, ro) | TT:145 EDS:703 | high
2087_00 | commMeteringInterval Meter value sample interval (s) | TT:146 EDS:707 PanelConnectivity.cs:627(8327) | high
2088_00 | commMeteringTransmissionMode 0=End 1=During 2=Always | TT:147 EDS:713 PanelConnectivity.cs:648(8328) | high
2089_00 | commMeteringAlignment 0=Boot 1=Clock | TT:148 EDS:737 PanelConnectivity.cs:649(8329) | high
208A_00 | commPingPongInterval Ping pong interval (s, min 30) | TT:149 EDS:755 PanelConnectivity.cs:589(8330) | high
208B_01 | commWebSocketTimeout:wired Wired websocket timeout (s) | TT:150 PanelConnectivity.cs:591(8331,1) | high
208B_02 | commWebSocketTimeout:gprs Mobile websocket timeout (s) | TT:151 PanelConnectivity.cs:592 | high
208D_01 | commRpcConnectTimeout:wired Wired OCPP send timeout (s) | TT:152 PanelConnectivity.cs:593(8333,1) | high
208D_02 | commRpcConnectTimeout:gprs Mobile OCPP send timeout | TT:153 PanelConnectivity.cs:594 | high
208E_01 | commRpcReplyTimeout:wired Wired OCPP reply timeout (s) | TT:154 PanelConnectivity.cs:595(8334,1) | high
208E_02 | commRpcReplyTimeout:gprs Mobile OCPP reply timeout | TT:155 PanelConnectivity.cs:596 | high
208F_00 | commCentralMeteringInterval Central meter sample interval (s) | TT:156 PanelConnectivity.cs:647(8335) | high
2090_00 | commMeteringFinalDelivery Final Delivery | EDS:761 | medium
2091_00 | commMeteringMaxValues Max Metering Values | EDS:779 | medium
2092_00 | commOptionalMeteringInterval Metering Interval [Optional] | EDS:785 | medium
2093_00 | commSendStationStatus Send station status | TT:157 EDS:791 PanelConnectivity.cs:605(8339) | high
2094_00 | commConcurrentTxAction Abort concurrent transaction | TT:96 EDS:809 PanelAuthorization.cs:331(8340) | high
2095_00 | commStopTransactionOnInvalidId Stop transaction on invalid tag | TT:97 PanelAuthorization.cs:330(8341) | high
2096_00 | commTransactionMessageAttempts Message attempts | TT:158 PanelConnectivity.cs:626(8342) | high
2097_00 | commTransactionMessageRetryInterval Message retry interval (s) | TT:159 PanelConnectivity.cs:627(8343) | high
2098_01..09 | SampledData_1..9 sampled measurand slots (value=measurand|phase<<16) | TT:160-168 PanelConnectivity.cs:634-637(8344,sub, mask 65535) | high
2099_01..09 | AlignedData_1..9 clock-aligned measurand slots | TT:169-177 PanelConnectivity.cs:640-643(8345) | high
209A_00 | commClockAlignedDataInterval Clock aligned data interval (s) | TT:178 PanelConnectivity.cs:624(8346) | high
209B_00 | commAuthorizeRemoteTxRequests Remote transaction requests | TT:98 PanelAuthorization.cs:329(8347) | high
209C_00 | commStatusNotificationMethod 0=Normal 1=Immediate timestamp 2=Queued | TT:179 PanelConnectivity.cs:623(8348) | high
209D_00 | commForceHeartBeats Send always heartbeat | TT:180 PanelConnectivity.cs:587(8349) | high
209E_00 | gprsSupportedRATs (inferred) supported RAT bitmask 1=GPRS 2=UMTS 4=LTE | PanelConnectivity.cs:924(2137600=0x209E00) ICULanDevice.cs:2928-2932(8350) | medium
209F_00 | gprsActualRAT Mobile Technology in use 0=2G 1=3G 2=4G | TT:300 PanelMonitoring.cs:347(8351) PanelBase.cs:100-103 | high
20F0_01..16 | comNetworkProfile1 block: sub1=boVersion(2=OCPP1.5,3=OCPP1.6,4=OCPP2.0.1) sub3=csmsUrl sub4=messageTimeout sub5=securityProfile(0-3) sub6=boInterface sub7=APNname sub8/15=APNuser sub9=APNpassword sub10/16=SIMpin sub14=priority(0=not used,1-4) | TT:181-186 PanelConnectivity.cs:720-735,66-80(ENPSubIds) | high
20F3_* | comNetworkProfile4 block (same layout) | PanelConnectivity.cs:2935-2950 loop 8432..8435 | high
20F4_00 | commNetworkProfileConnectionAttempts attempts before profile switch | TT:187 PanelConnectivity.cs:462(8436) | high
2100_00 | gprsAPNname APN name (wo UI) | TT:188 EDS:812 PanelConnectivity.cs:510(8448) | high
2101_00 | gprsAPNuser APN user (wo UI) | TT:189 EDS:818 PanelConnectivity.cs:511(8449) | high
2102_00 | gprsAPNpassword APN password (wo UI) | TT:190 EDS:824 PanelConnectivity.cs:512(8450) | high
2103_00 | gprsSIMpin SIM pin (wo UI) | TT:191 EDS:830 PanelConnectivity.cs:513(8451) | high
2104_00 | gprsSIMimsi SIM IMSI (ro) | TT:192 EDS:836 PanelConnectivity.cs:608(8452) | high
2105_00 | gprsSIMiccid SIM ICCID (ro) | TT:193 EDS:842 PanelConnectivity.cs:609(8453) | high
2106_00 | gprsConnectDelay | EDS:848 | medium
2107_00 | gprsConnectAttempts | EDS:854 | medium
2108_00 | gprsConnectRetryBehaviour | EDS:860 | medium
2109_00 | gprsBand 0=Auto 1=900MHz 2=1800MHz 3=1900MHz | EDS:878-907 | medium
2110_00 | gprsSignalStrength Mobile signal strength (dBm, ro) | TT:194 EDS:908 PanelConnectivity.cs:607(8464) | high
2111_00 | gprsWeakSignalThreshold (dBm) | EDS:914 | medium
2112_00 | gprsProvider Network Operator (ro) | EDS:921 | medium
2113_00 | gprsNetworkSelection 0=Automatic 1=Manual | TT:195 PanelConnectivity.cs:692(8467) | high
2114_00 | gprsNetworkPreference 0=2G 1=4G | TT:196 PanelConnectivity.cs:693(8468) | high
2115_00 | proxyDomainPort Proxy address and port | TT PanelConnectivity.cs:588(8469) | high
2116_00 | proxyUsername Proxy user name | TT PanelConnectivity.cs:592(8470) | high
2116_01 | ProxyPassword Proxy password (WRITE-ONLY) | TT PanelConnectivity.cs:596(key 0x211601) | high
2117_00 | proxyEnable Proxy enabled | TT PanelConnectivity.cs:584(8471) | high
2118_00 | modemManufacturer (ro) | TT:197 PanelInformation.cs:394(8472) | high
2119_00 | modemModel (ro) | TT:198 PanelInformation.cs:395(8473) | high
2120_00 | modemRevision (ro) | TT:199 PanelInformation.cs:396(8480) | high
2121_00 | modemIMEI (ro) | TT:200 PanelInformation.cs:397(8481) | high
2124_00 | commInformationalStatusNotifications Send informational notifications | TT:201 PanelConnectivity.cs:609(8484) | high
2125_00 | mainSocketType Connector type sock1: 0=Fixed Cable 1=Balz/Mennekes 2=FCT 3=Schuko 4=FCT1 5=FCT2 6=CCS 7=ChaDeMo | TT:27 EDS:927-952 PanelPower.cs:270(8485) | high
2126_00 | mainAuthorizationMethod 0=Plug&Charge 1=RFID Reader 2=Communication Unit 3=Button | TT:99 EDS:984-1012 PanelAuthorization.cs:311(8486) | high
2127_00 | mainOfflineNFCAuthorization high bit; combined (2127<<1)+213E → 0=Refuse all 1=Accept known 3=Accept all | TT:100 EDS:1014 PanelAuthorization.cs:343,598-629(8487,8510) | high
2128_00 | mainStartMaxCurrent Start max current (A) | EDS:1032 CFG:23 | high
2129_00 | mainNormalMaxCurrent Max current (A) connector 1 | TT:28 EDS:1039 PanelPower.cs:263(8489) | high
212A_00 | mainExternalMaxCurrent external set current (A, RAM rw) | EDS:1054 | high
212B_00 | mainLoadBalancingMaxCurrent LB max current (A, ro) | EDS:1058 | high
212C_00 | mainActiveMaxCurrent active max current (A, ro) | EDS:1065 | high
212D_00 | mainP1BalancingMaxCurrent P1 balancing max current (A, ro) | EDS:1069 | high
2130_00 | mainSimplifiedMaxCurrent (A) | EDS:1076 CFG:25 | high
2131_00 | mainStartupDelay (sec) | EDS:1083 | medium
2132_00 | mainSwitchErrorTime (sec) | EDS:1090 | medium
2133_00 | mainCurrentErrorTime (sec) | EDS:1097 | medium
2134_00 | mainHFContactorSwitchTime (sec) | EDS:1104 | medium
2135_00 | mainEVConnectTimeout Connection timeout (s) | TT:101 EDS:1111 PanelAuthorization.cs:332(8501) | high
2136_00 | mainEVDisconnectTimeout Disconnect timeout (s) | TT:102 EDS:1118 PanelAuthorization.cs:287(8502) | high
2137_00 | mainEVDisconnectAction 0=Continue 1=Abort Lock 2=Abort Unlock 3=Abort Unlock When Offline | TT:103 EDS:1125-1152 PanelAuthorization.cs:285(8503) | high
2138_00 | mainNFCreaderType 0=None 1=miFrame Easy 2=Alfen | EDS:1153-1176 | medium
2139_00 | mainNFCreaderScanInterval (msec) | EDS:1177 | medium
213A_00 | mainNFCreaderModel (ro) | EDS:1184 | medium
213B_00 | mainWhiteListEnabled White list enabled | TT:104 EDS:1187 PanelAuthorization.cs:315(8507) | high
213C_00 | mainOnlineNFCAuthorization 0=Pre Authorize local lists 1=Wait for BackOffice | TT:105 PanelAuthorization.cs:341(8508) | high
213D_00 | mainLocalListEnabled Local list enabled | TT:106 PanelAuthorization.cs:316(8509) | high
213E_00 | offline NFC auth low bit (paired with 2127_00) | PanelAuthorization.cs:598-604(8510) | medium
213F_00 | authorizationTimeout Authorization timeout (s) | TT:107 PanelAuthorization.cs:336(8511) | high
2140_00 | mainNFCreaderTagDelay (msec) | EDS:1205 | medium
2142_00 | mainBuzzerTime (msec) | EDS:1212 | medium
2143_00 | mainBuzzerErrorTime (msec) | EDS:1219 | medium
2144_00 | mainBuzzerErrorCount | EDS:1226 | medium
2145_00 | mainPWMStartTime (msec) | EDS:1232 | medium
2146_00 | mainPWMWaitTime (msec) | EDS:1239 | medium
2147_00 | mainPWMTerminateTime (msec) | EDS:1246 | medium
2148_00 | mainPWMWakeUpTime (msec) | EDS:1253 | medium
2149_00 | mainPWMWakeUpDuration (msec) | EDS:1260 | medium
2150_00 | mainPWMStateB1Time (msec) | EDS:1267 | medium
2151_00 | mainChargingTriacStartTime (msec) | EDS:1274 | medium
2152_00 | mainChargingTriacKeepTime (msec) | EDS:1281 | medium
2153_00 | mainChargingMaxTimeToOpenS2 (msec) | EDS:1288 | medium
2154_00 | mainChargingOutputVoltageCheckTime (msec) | EDS:1295 | medium
2155_00 | mainChargingMaxRestarts | EDS:1302 | medium
2156_00 | mainErrorMessageTime (sec) | EDS:1308 | medium
2159_00 | mainZEready ZE ready (bool) | TT:29 EDS:1315 PanelPower.cs:302(8537) | high
215A_00 | mainPartySwitchDelay (ms) | EDS:1333 | medium
215B_00 | mainControlPilotFilter | EDS:1340 | medium
215C_00 | mainCheckExternalRCB RCB position input | EDS:1346 | medium
215D_00 | mainDisableOvercurrentCheck105 Disable 105% overcurrent | TT:30 PanelPower.cs:303(8541) | high
215E_00 | mainRestartAfterPowerOutage Restart after Power Outage | TT:108 PanelAuthorization.cs:317(8542) | high
2165_01 | Static LB checkbox (AHP variant) | PanelLoadbalancing.cs:601(0x206501) | medium
2168_00 | mainAutoStopTransactionTime Time to unlock not charging (s) | TT:109 PanelAuthorization.cs:300(8552) | high
2169_00 | mainMaxAllowedOutageDuration Re-authorize after Power Outage (s) | TT:110 PanelAuthorization.cs:318(8553) | high
216A_00 | mainSignedDataEnabled Eichrecht enabled (one-way) | TT:202 EDS:1352 PanelConnectivity.cs:661(8554) | high
216B_00 | mainSignedMeterValueUpdates Signed meter values | TT:203 PanelConnectivity.cs:666(8555) | high
216C_00 | mainP1PortUse Direct external suspend signal 0=Not allowed 1=suspend when closed 2=suspend when open | TT:31 EDS tail PanelPower.cs:245 area(0x216C00) | high
216E_00 | mainQRCodeURL QR code base URL | TT:204 PanelConnectivity.cs:673(8558) | high
216F_00 | mainSignedStartStopMeterValue Signed meter values at Start&Stop | TT:205 | high
2170_03 | mainRequest:LocalDBRequest Transaction Database: write 2=Clear | EDS:1325-1340 | high
2170_04 | mainRequest:ResetRequest write 2=Reboot 3=Reset firmware | EDS:1342-1358 | high
2171_00 | mainLEDHeartBeatMode Heart beat mode enabled | TT PanelInterface.cs:237(8561) | high
2172_00 | mainLEDHeartBeatIntensity Heart beat intensity % | TT PanelInterface.cs:238(8562) | high
2173_00 | mainTypeEMaxCurrent1 Connector 1.2 (Type-E) max current (A) | TT:32 PanelPower.cs:268(8563) | high
2174_01 | MaxImbalanceCurrent enable (bool) | TT:45 PanelPower.cs:250(0x217401) | high
2174_02 | MaxImbalanceCurrent Maximum Imbalance Current (A, 0=disabled) | TT:46 PanelPower.cs:251(0x217402, 8564) | high
2177_00 | QRCodeURL1 QR Code URL Socket 1 | TT:115 PanelAuthorization.cs:370(8567) | high
2178_00 | QRCodeURL2 QR Code URL Socket 2 | TT:116 PanelAuthorization.cs:372(8568) | high
2180_01 | SCN_NetworkName Network Name (empty=not in SCN) | TT:54 EDS:1395 PanelLoadbalancing.cs:757 | high
2180_02 | SCN_SocketId SCN Socket ID | TT:59 EDS:1400 PanelLoadbalancing.cs:775 | high
2180_03 | SCN_NumberOfSockets number of sockets in SCN | TT:60 EDS:1405 PanelLoadbalancing.cs:776 | high
2180_04 | SCN_AlternatingPeriod Alternating period (s 900-36000) | TT:58 EDS:1410 PanelLoadbalancing.cs:772 PanelSCNSettings.cs:386 | high
2180_05 | SCN_MaxStaticAvailableCurrent Total current (A) | TT:55 EDS:1425 PanelLoadbalancing.cs:760 | high
2180_06 | SCN_UnconnectedSafeCurrent Socket Safe current (A) | TT:56 EDS:1430 PanelLoadbalancing.cs:763 | high
2180_07 | SCN_PhaseMapping1 0=None 1=L1 2=L2 3=L3 4=L1L2L3 5=L1L3L2 6=L2L1L3 7=L2L3L1 8=L3L1L2 9=L3L2L1 | TT:61 EDS:1440-1465 DlgSCNPhaseMapping.cs:87,194 | high
2180_08 | SCN_isUnlocked flag 0/1 | EDS:1467 | low (EDS dup-id anomaly)
2180_09 | SCN_PhaseMapping2 (same options) | TT:62 EDS:1479 DlgSCNPhaseMapping.cs:88,196 | high
2180_0A | SCN_UnconnectedSafeCurrentTotal Total safe current (A) | TT:57 PanelLoadbalancing.cs:768 PanelSCNSettings.cs:389(8576,10) | high
2181_00 | mainRCDDelayTime RCD delay time (s) | TT:278 PanelAlerts.cs:90(8577) | high
2182_00 | mainMaxTxMeterValueRandomisationTime Random mv clock aligned msg (s) | TT:206 PanelConnectivity.cs:629(8578) | high
2183_00 | mainCoverLockEnabled Cover lock enabled | TT PanelInterface.cs:241(8579) | high
2184_00 | mainNonChargingReportThreshold Time to report not charging (s) | TT:111 PanelAuthorization.cs:296(8580) | high
2185_00 | mainEnablePhaseSwitching Allow single-/multiphase charging | TT:87 PanelLoadbalancing.cs:696(8581) | high
2187_00 | mainLastConfigurationChange Last time config changed (ms epoch, ro) | TT:7 PanelInformation.cs:307(8583) ICULanDevice.cs:300-303 | high
2188_00 | mainDPSGiroeMethodStatus Giro-e state 0=DISABLED 1=ENABLED 2=OFFLINE | TT:112 PanelMonitoring.cs:352(8584) EGiroEState.cs | high
2189_00 | mainMaxAllowedPhases 1=1-Phase 3=3-Phase (AHP also 2) reboot req | TT:33 EDS tail PanelPower.cs:240(8585) | high
2190_00 | mainNFCLedEnabled 0=Disabled 1=Both 2=UI LED | EDS:1513-1531 PanelInterface.cs:221-228(8592) | high
2191_01 | mainP1Interface:interface 0=Serial 1=Telnet 2=HomeWizard Wi-Fi P1 | TT:63 PanelLoadbalancing.cs:787(8593,1) | high
2191_02 | mainP1Interface:serveraddress P1 IP address | TT:64 PanelLoadbalancing.cs:790 LogHttpClientHandler.cs:36 | high
2191_03 | mainP1Interface:serverport P1 port | TT:65 PanelLoadbalancing.cs:791 | high
2192_00 | remotePaymentOptions flags 0=None 1=OTS 2=QRCode 4=GiroE | TT:114 PanelAuthorization.cs:356-359(8594) EDirectPaymentOptions.cs | high
21A0_00 | ObjectID unique 64-bit device ID (license purchase) | DlgUnlockFeature.cs:76(8608) DlgObjectID.cs:104 | high
21A1_00 | sysFeatureCode Feature license key (rw) | TT:19 DlgUnlockFeature.cs:56,108,160(8609) | high
21A2_00 | sysFeatureRequest/unlocked features bitfield: 0x200=ISO15118 0x1000=PersonalizedDisplay 0x10000=Mobile3G4G 0x100000=Payment_Options 0x1000000=Expose_SmartMeterData 0x80000000=ObjectID (+LoadBalancing_Active/SCN, RFIDReader bits) | DlgUnlockFeature.cs:90 MainWindow.cs:1134 IWSFirmwareFeatures.cs:17-22 PanelInterface.cs:305(0x21A200) | high
21B0_00 | sysPEDETEnabled Strict PE Measurement | TT:291 EDS:1514 PanelAlerts.cs(0x21B000) | high
21B1_00 | systargetRDP RDP target level 0/1/2 | EDS:1524 PanelInformation.cs:636-638(8625) | high
21B2_00 | sysServiceEnabled Enable Secure Service Access SSA | TT:207 EDS:1541 PanelInformation.cs:458(8626) | high
21B3_00 | sysTempAccessExpiration temp password expiration (ro) | TT:208 PanelInformation.cs:460(8627) | high
21B4_00 | sysIsAdminPWDefault 0=Default 1=Custom (ro) | TT:209 PanelInformation.cs:463(8628) | high
21B5_00 | sysModemEnabled (ro) | TT:210 | high
21B6_00 | sysOperationalTime System uptime (s, ro) | TT:211 | high
21B7_00 | sysSecureEEPROM | TT:212 | medium
21B8_00 | auxBoardInfo bitmask bit1=supported bit2=communicating | TT:213 | high
21B9_00 | chargingProfileMaxRandomDelay Random delay (s, UK smart charging) | TT:214 PanelLoadbalancing.cs:809(8633) | high
2200_00 | sensTemperatureMode 0=None 1=Automatic | EDS:1561 | medium
2201_00 | sensTemperatureValue measured temp (°C, ro) | TT:295 EDS:1585 PanelMonitoring.cs:485(8705) | high
2202_00 | sensTemperatureAlarmLow (°C, def -25) | TT:280 EDS:1604 PanelAlerts.cs:67(8706) | high
2203_00 | sensTemperatureAlarmHigh (°C, def 70) | TT:281 EDS:1611 PanelAlerts.cs:66(8707) | high
2204_00 | sensTemperatureCheckInterval (s) | TT:282 EDS:1618 PanelAlerts.cs:68(8708) | high
2205_00 | sensTemperatureLogInterval (s) | TT:283 EDS:1625 PanelAlerts.cs:70(8709) | high
2206_00 | sensAccelerometerMode tilt mode 0=None 1=Automatic-OFF 2=Automatic-ON | TT:284 EDS:1632 PanelAlerts.cs:73(8710) PanelMonitoring.cs:126,628 | high
2207_00 | sensAccelerometerValueX tilt actual X | TT:296 EDS:1653 PanelMonitoring.cs:634(8711) | high
2208_00 | sensAccelerometerValueY | EDS:1658 PanelMonitoring.cs:634(8712) | high
2209_00 | sensAccelerometerValueZ | EDS:1663 PanelMonitoring.cs:634(8713) | high
2210_00 | sensAccelerometerSetpointX tilt setpoint X | TT:289 EDS:1668 PanelAlerts.cs:132(8720) | high
2211_00 | sensAccelerometerSetpointY | PanelAlerts.cs:133(8721) EDS:1673 | high
2212_00 | sensAccelerometerSetpointZ | PanelAlerts.cs:134(8722) EDS:1678 | high
2213_00 | sensAccelerometerMarginX Margin X | TT:285 EDS:1682 PanelAlerts.cs:75(8723) | high
2214_00 | sensAccelerometerMarginY | TT:286 EDS:1687 PanelAlerts.cs:76(8724) | high
2215_00 | sensAccelerometerMarginZ | TT:287 EDS:1692 PanelAlerts.cs:77(8725) | high
2216_00 | sensAccelerometerLogInterval (s) | TT:288 EDS:1697 PanelAlerts.cs:78(8726) | high
2217_00 | sensEnergyMeterType socket1 meter type (ro) | EDS:1702 | medium
2218_00 | sensEnergyMeterModbusType socket1 Modbus brand: 0=Pulse 1=ABB 4=Saia 5=Carlo Gavazzi 7=IVU 8=DZG DVH4013/Reallin 9=Socomec | CFG:47 EDS:1791-1838 PanelPower.cs:320(8728=='IVU') | high
2221_01 | meter1 TimeStamp (s, ro) | EDS:1932 | high
2221_03 | meter1_voltageL1N Voltage L1-N (V) | TT:301 EDS:1972 PanelMeterValues.cs:57(8737,3) | high
2221_04 | meter1_voltageL2N (V) | TT:302 PanelMeterValues.cs:58 | high
2221_05 | meter1_voltageL3N (V) | TT:303 PanelMeterValues.cs:59 | high
2221_06 | meter1_voltageL1L2 (V) | TT:304 EDS:1993 | high
2221_07 | meter1_voltageL2L3 (V) | TT:305 EDS:2000 | high
2221_08 | meter1_voltageL3L1 (V) | TT:306 EDS:2007 | high
2221_09 | meter1_currentN Current N (A) | TT:307 EDS:2014 | high
2221_0A | meter1_currentL1 Current L1 (A) | TT:308 DlgSmartMeterTest.cs:40(sub10 div1) | high
2221_0B | meter1_currentL2 (A) | TT:309 DlgSmartMeterTest.cs:41 | high
2221_0C | meter1_currentL3 (A) | TT:310 DlgSmartMeterTest.cs:42 | high
2221_0E | meter1_cosPhiL1 power factor L1 | TT:311 | high
2221_0F | meter1_cosPhiL2 | TT:312 | high
2221_10 | meter1_cosPhiL3 | TT:313 | high
2221_11 | meter1_cosPhiSum average | TT:314 | high
2221_12 | meter1_frequency Frequency (Hz) | TT:315 | high
2221_13 | meter1_powerRealL1 Active Power L1 (kW) | TT:316 DlgSmartMeterTest.cs:43(sub19 div1000) | high
2221_14 | meter1_powerRealL2 (kW) | TT:317 DlgSmartMeterTest.cs:44 | high
2221_15 | meter1_powerRealL3 (kW) | TT:318 DlgSmartMeterTest.cs:45 | high
2221_16 | meter1_powerRealSum Active Power Total (kW) | TT:319 | high
2221_22 | meter1_energyRealDeliveredSum (kWh) | EDS:2056 | high
2221_26 | meter1_energyRealConsumedSum (kWh) | EDS:2063 | high
2224_00 | sensADCVoltageCP1High CP voltage high (V, ro) | EDS:2385 | medium
2225_00 | sensADCVoltageCP1Low CP voltage low (V, ro) | EDS:2392 | medium
2228_00 | sensADCVoltageCP2High | EDS:2399 | medium
2229_00 | sensADCVoltageCP2Low | EDS:2403 | medium
2231_00 | sensADCResistancePP1 PP resistance (Ω, ro) | EDS:2407 | medium
2233_00 | sensADCResistancePP2 (Ω, ro) | EDS:2411 | medium
2247_03 | sensValues_CP_PP:PP PP resistance | EDS:2415 | medium
2247_04 | sensValues_CP_PP:DC PWM duty cycle | EDS:2422 | medium
2249_00 | sensTemperatureMeasured:max Max measured temp (ro) | TT:320 PanelMonitoring.cs:489(8777,0) | high
2249_01 | sensTemperatureMeasured:min Min measured temp (ro) | TT:321 PanelMonitoring.cs:490(8777,1) | high
2250_00 | sensTamper 0=Unknown 1=Not tampered 2=Tamper active 3=Tampered 4=Tampered acknowledged (write 4 to ack) | TT:290 PanelAlerts.cs:58-62,101 MainWindow.cs:1095-1104 ETamperState.cs | high
2251_01 | TamperDetectionAvailable (ro) | TT:117 PanelInformation.cs:326,385(8785,1) | high
2251_02 | TamperDetectionMode 0=Disabled 1=Strict 2=Authorization | TT:118 EDS tail PanelAuthorization.cs:380-382(8785,2) | high
2300_00..2336_0A | LED colour presets per LED-state block (NOT socket capacity): 2300=Unknown 2301=Off 2302=Booting 2303=BootingCheckMains 2304=Available 2305=PrepAuthorising 2306=PrepAuthorised 2307=PrepCableConnected 2308=PrepEVConnected 2309=ChargingPreparing 2310=ChargingWaitVehicle 2311=ChargingActiveNormal 2312=ChargingActiveSimplified 2313=ChargingSuspendedOverCurrent 2314=ChargingSuspendedHFSwitching 2315=ChargingSuspendedEVDisconnected 2316=FinishWaitVehicle 2317=FinishWaitDisconnect 2318=ErrorProtectiveEarth 2319=ErrorPowerlineFault 2320=ErrorContactorFault 2321=ErrorCharging 2322=ErrorPowerFailure 2323=ErrorTemperature 2324=ErrorIllegalCPValue 2325=ErrorIllegalPPValue 2326=ErrorTooManyRestarts 2327=Error 2328=ErrorMessage 2329=ErrorMessageNotAuthorised 2330=ErrorMessageCableNotSupported 2331=ErrorMessageS2NotOpened 2332=ErrorMessageTimeOut 2333=Reserved 2334=InOperative 2335=LoadBalancingLimited 2336=LoadBalancingForcedOff. Each block: sub1=red1 sub2=green1 sub3=blue1 sub4=cyan1 sub5=duration1 sub6=red2 sub7=green2 sub8=blue2 sub9=cyan2 subA=duration2 (u8 0-255 rw) | EDS:2413-2560+ full ParameterNames; mirrors ELEDStates enum | high
2400_01 | masterTagVars:isEnabled Master card mode | TT:113 PanelAuthorization.cs:351(9216,1) ICUMasterTag.cs:44 | high
2400_02 | masterTagVars:id master tag identifier | ICUMasterTag.cs:22,71(9216,2) | medium
2501_01 | socket1_StateMain Main state (EMainStates) | TT:322 PanelMonitoring.cs:282(9473,1) | high
2501_02 | socket1_StateLeds LED state (ELEDStates) | TT:324 PanelMonitoring.cs:283(9473,2) | high
2501_03 | socket1_StateSocket Power state: fw<7.3 ESocketStates(-1..4); fw>=7.3 0=OFF 1=ON | TT:325 PanelMonitoring.cs:286,290(9473,3) | high
2501_04 | socket1_StateMode3 Mode3 state (EMode3States) | TT:323 PanelMonitoring.cs:281(9473,4) | high
2501_05 | socket1_StateCC CC state (AHP, EAHWPCCStates) | PanelMonitoring.cs:273(9473,5) | high
2501_63 | display_Status device error code display (TT labels 2501_99=0x63) | TT:326 | high
2502_01 | socket2_StateMain | TT:330 PanelMonitoring.cs:328(9474,1) | high
2502_02 | socket2_StateLeds | TT:331 PanelMonitoring.cs:329 | high
2502_03 | socket2_StateSocket | TT:332 PanelMonitoring.cs:332,336 | high
2502_04 | socket2_StateMode3 | TT:329 PanelMonitoring.cs:327 | high
2502_63 | display_Status socket2 error code | TT:327 | high
2511_00 | socket1_CP_PP_CPhigh CP voltage high (V) | TT:328 | high
2511_01 | socket1_CP_PP_CPlow CP voltage low (V) | TT:329 | high
2511_02 | socket1_CP_PP_PP PP resistance (Ω) | TT:331 | high
2511_03 | socket1_CP_PP_DC PWM duty cycle (%) | TT:332 | high
2512_00 | socket2_CP_PP_CPhigh (V) | TT:333 | high
2512_01 | socket2_CP_PP_CPlow (V) | TT:334 | high
2512_02 | socket2_CP_PP_PP (Ω) | TT:335 | high
2512_03 | socket2_CP_PP_DC PWM (%) | TT:339 | high
2522_01 | MbusTCP1_enabled ModbusTCP balancing enabled | TT:66 EDS:203 PanelLoadbalancing.cs:658(9506,1) | high
2522_02 | MbusTCP1_SlaveType 1=Socomec(Countis E27) 2=Custom register mapping | TT:67 EDS:206 PanelLoadbalancing.cs:704(9506,2) | high
2522_03 | MbusTCP1_ConnectionType 0=Modbus_master_TCP 1=Modbus_Master_RTU 2=Modbus_Master_UDP | TT:68 EDS:215 PanelLoadbalancing.cs:709(9506,3) | high
2522_04 | MbusTCP1_IPaddress meter IP | TT:69 PanelLoadbalancing.cs:711(9506,4) PanelPower.cs:314 | high
2522_06 | MbusTCP1_SlaveAddress slave address | TT:70 PanelLoadbalancing.cs:712(9506,6) | high
2523_02 | MbusTCP2_SlaveType 1=Socomec 2=Custom | TT:71 EDS:230 PanelLoadbalancing.cs:726(9507,2) | high
2523_03 | MbusTCP2_ConnectionType | EDS:239 | high
2523_04 | MbusTCP2_IPaddress external meter IP | TT:72 PanelLoadbalancing.cs:719(9507,4) | high
2523_06 | MbusTCP2_SlaveAddress | TT:73 PanelLoadbalancing.cs:720(9507,6) | high
2530_01 | modbusTCPIPSlave:options Data Source 0=Meter 1=Meter+EMS Monitoring 3=EMS | TT:83 EDS:1748 PanelLoadbalancing.cs:644(9520,1) ICULanDevice.cs:569 | high
2530_03 | modbusTCPIPSlave:SCNEnable EMS mode 1=SCN 2=Socket | TT:84 PanelLoadbalancing.cs:742(0x253003) | high
2530_04 | modbusTCPIPSlave:validityTime EMS validity time (s) | TT:85 PanelLoadbalancing.cs:747(9520,4) | high
2540_00 | modbusSlave1ConnectionState 0=IDLE 1=INITIALIZING 2=NORMAL 3=WARNING 4=ERROR (ro) | TT:340 PanelMonitoring.cs:251(9536) EModbusTCPIPConnectionStates.cs | high
2541_00 | energyMeterPublicKey1 socket1 public key (ro) | TT:34,224 PanelPower.cs:323(9537) PanelConnectivity.cs:670 | high
2542_00 | energyMeterPublicKey2 socket2 public key (ro) | TT:35,225 PanelConnectivity.cs:671(9538) | high
2560_00..2563_xx | central-meter Modbus register mapping block (9568-9571) | ICUModbusRegmap.cs:37-40 | medium
2570_00..2573_xx | smart-meter register mapping block (9584-9587) | ICUModbusRegmap.cs:37-40 | medium
2574_00 | modbusSmartMeterConfig:wordOrder 0=High to Low 1=Low to High | TT:74 EDS tail PanelLoadbalancing.cs:730(9588,0) | high
2574_01 | modbusSmartMeterConfig:updateTime RTU update time (ms) | TT:75 PanelLoadbalancing.cs:809(9588,1) | high
2574_02 | modbusSmartMeterConfig:readtimout RTU read timeout (ms) | TT:76 PanelLoadbalancing.cs:810(9588,2) | high
2574_03 | modbusSmartMeterConfig:functionCode 3=Holding 4=Input Registers | TT:77 EDS tail PanelLoadbalancing.cs:811(9588,3) | high
2575_00 | modbusSmartMeterUart:baudrate 2400/4800/9600/14400/19200/38400/57600/115200/128000/256000 | TT:78 EDS tail PanelLoadbalancing.cs:807(9589,0) | high
2575_01 | modbusSmartMeterUart:parity 0=None 1=Even 2=Odd | TT:79 PanelLoadbalancing.cs:806(9589,1) | high
2575_02 | modbusSmartMeterUart:address RTU address (string) | TT:80 PanelLoadbalancing.cs:805(9589,2) | high
2610_00 | allowAlphaRelease Allow alpha releases | TT:22 PanelInformation.cs:496(9744, 0x261000) | high
2620_00 | signedenergydataincludepublickey 0=Never 1=Once per transaction 2=Every meter value | TT:223 EDS:1370 PanelConnectivity.cs:667(9760) | high
2621_00 | stoptxincludesignedalignedenergydata (bool) | TT:224 EDS:1382 PanelConnectivity.cs:669(9761) | high
2700_00 | securitySSLCACertificate CA cert (octet) | EDS:~2820 | medium
2701_00 | securitySSLPreSharedKey (WRITE-ONLY, wo) | EDS:~2826 | medium
2702_00 | securitySSLAuthenticationMethod 0=None 1=CA Certificate | EDS:~2830 | medium
2722_00 | securityCpoName CPO name (certificate) | TT:219 PanelConnectivity.cs:558(10018) | high
2723_00 | securitySecurityProfile 0=Default 1=Unsecure+BasicAuth 2=TLS+BasicAuth 3=TLS+ClientCert (increase only) | TT:220 PanelConnectivity.cs:562(10019) | high
2723_01 | BackOfficeAuthorizationKey Basic auth key (WRITE-ONLY) | TT:221 PanelConnectivity.cs:566(0x272301) | high
2903_00 | fileGetDiagnosticsRetrieve | EDS tail | medium
2910_00 | fileFirmwareUpdateCommand (u8 rw) | EDS tail | medium
2911_00 | fileFirmwareUpdateStatus ro: -4=rolled back -3=rollback -2=error update -1=error upload 0=none 1=erasing 2=erased 3=ready upload 4=uploading 5=checking 6=wait service mode 7=ready 8=in progress 9=ready to roll 10=done 11=CRC calc 12=CRC done | EDS tail (full options) | high
2912_00 | fileFirmwareUpdateUpload Update firmware (wo) | EDS tail | high
2913_00 | fileWhiteList | EDS tail | medium
2914_00 | fileTransactions (ro) | EDS tail | medium
2915_00 | fileFirmwareBufferCRC (ro) | EDS tail | medium
3125_00 | mainSocketType2 connector type sock2 (options as 2125) | TT:36 EDS:954 PanelPower.cs:292(12581) | high
3129_00 | mainNormalMaxCurrent2 Max current (A) connector 2 | TT:37 PanelPower.cs:285(12585) | high
312E_00 | mainMaxNrPhases1 Max phases sock1 (ro) | TT:40 PanelPower.cs:273(12590) | high
312F_00 | mainMaxNrPhases2 Max phases sock2 (ro) | TT:41 PanelPower.cs:295(12591) | high
3173_00 | mainTypeEMaxCurrent2 Connector 2.2 max current (A) | TT:42 PanelPower.cs:290(12659) | high
3180_00 | mainNfcVersion1:HW NFC reader 1 HW version | TT:8 PanelInformation.cs:342(12672) | high
3180_01 | mainNfcVersion1:SW NFC reader 1 SW version | TT:9 PanelInformation.cs:343 | high
3181_00 | mainNfcVersion2:HW | TT:10 PanelInformation.cs:346(12673) | high
3181_01 | mainNfcVersion2:SW | TT:11 PanelInformation.cs:347 | high
3182_00 | mainBLVersion Bootloader version (ro) | TT:12 PanelInformation.cs:322(12674) | high
3190_01 | mainUserInterfaceMode1:state Display state socket 1 (EUserInterfaceStates, ro, fw>=4.4) | TT:341 PanelMonitoring.cs:295(12688,1) | high
3191_01 | mainUSerInterfaceMode2:state Display state socket 2 | TT:342 PanelMonitoring.cs:341(12689,1) | high
3217_00 | sensEnergyMeterType2 (ro) | EDS:1714 | medium
3218_00 | sensEnergyMeterModbusType2 (options as 2218) | CFG:48 EDS:1839 | high
3221_03..16 | meter2_* socket2 meter values (layout as 2221) | TT:343-360 PanelMeterValues.cs:42-43(12833) EDS 3221sub* | high
3258_00 | minStatusDuration Minimum Status Duration (s) | TT:222 PanelConnectivity.cs:613(12888) | high
3260_01 | dispDisplayInfo:displayPresent (inferred) display-present flag | ICULanDevice.cs:466,488(0x326001) | medium
3260_03 | display max logo width (px) | ICULanDevice.cs:468(12896,3) | high (name inferred)
3260_04 | display max logo height (px) | ICULanDevice.cs:469(12896,4) | high (name inferred)
3261_00 | dispDisplayItemsEnabled 0=None 1=Date-Time 2=Station Power 3=DT+Power 4=Identity 5=DT+Identity 6=Power+Identity 7=All | TT:259 EDS tail PanelInterface.cs:118(12897) | high
3262_01 | dispDisplayPricing:currency ISO 4217 | TT:260 PanelInterface.cs:124(12898,1) | high
3262_02 | dispDisplayPricing:startPrice | TT:261 PanelInterface.cs:130(12898,2) | high
3262_03 | dispDisplayPricing:energyPrice Price per kWh | TT:262 PanelInterface.cs:136(12898,3) | high
3262_04 | dispDisplayPricing:minutePrice Price per minute | TT:263 PanelInterface.cs:145(12898,4) | high
3262_05 | dispDisplayPricing:showPriceComponent flags 1=disclaimer 2=perKwh 4=perMinute 8=perSession 16=perOther 32=adhocOnlyDisclaimer | TT:264 PanelInterface.cs:159 ICULanDevice.cs:2967-2998 TariffDisplayOptionsType.cs | high
3262_06 | dispDisplayPricing:otherPrice Other price | TT:265 PanelInterface.cs:154(12898,6) | high
3262_07 | dispDisplayPricing:otherSpecifier Other price name | TT:266 PanelInterface.cs:153(12898,7) | high
3272_00 | certificateEntries number of certificates | TT:216 | medium
3273_00 | rateUnits rate units for ChargingSchedule | TT:217 | medium
3274_00 | chargingProfileEntries number of profiles | TT:218 | high
3278_01 | chargingProfileOverrides:socket1 0=Follow profile 1=Override (direct start) | TT:219 PanelLoadbalancing.cs:804(12920,1) | high
3278_02 | chargingProfileOverrides:socket2 | TT:220 PanelLoadbalancing.cs:805(12920,2) | high
3280_01 | sysSolarCharging:operationMode 0=Off 1=Comfort 2=Green (fw>=6.3) | TT:88 PanelLoadbalancing.cs:821(12928,1) | high
3280_02 | sysSolarCharging:greenShare (%) | TT:89 PanelLoadbalancing.cs:822(12928,2) | high
3280_03 | sysSolarCharging:comfortLevel (W, max 22000) | TT:90 PanelLoadbalancing.cs:823(12928,3) | high
3280_04 | sysSolarCharging:overrideSocket1 boost socket1 | TT:91 PanelLoadbalancing.cs:824(12928,4) | high
3280_05 | sysSolarCharging:overrideSocket2 boost socket2 | TT:92 PanelLoadbalancing.cs:825(12928,5) | high
3284_00 | sysWifiEnabled 0=Disabled 1=Enabled 255=Not initialized | TT:228 EDS tail PanelConnectivity.cs:526(12932) | high
3285_01 | commIPaddress3:Value WiFi IP | TT:229 PanelConnectivity.cs:537(12933,1) | high
3285_02 | commIPaddress3:isFixed WiFi fixed IP | TT:230 PanelConnectivity.cs:534(12933,2) | high
3286_01 | commNetMask3:Value WiFi netmask | TT:231 PanelConnectivity.cs:538(12934,1) | high
3287_01 | commGWaddress3:Value WiFi gateway | TT:232 PanelConnectivity.cs:539(12935,1) | high
3288_01 | commDNS3_1:Value WiFi DNS1 | TT:233 PanelConnectivity.cs:540(12936,1) | high
3289_01 | commDNS3_2:Value WiFi DNS2 | TT:234 PanelConnectivity.cs:541(12937,1) | high
328A_00 | wifiSSID WiFi SSID | TT:235 EDS tail PanelConnectivity.cs:528(12938) | high
328B_00 | wifiPSK WiFi password (WRITE-ONLY; stored via SetProperty(12939)) | TT:236 EDS tail PanelConnectivity.cs:529(0x328B00),:1173 | high
328C_00 | wifiSecurity 2097154=WPA PSK TKIP 2097156=WPA PSK AES 2097158=WPA PSK AES&TKIP 4194306=WPA2 TKIP 4194308=WPA2 AES 4194310=WPA2 AES&TKIP 6291460=WPA2 WPA AES 6291462=WPA2 WPA AES&TKIP 16777220=WPA3 PSK AES 20971524=WPA3 WPA2 AES | TT:237 EDS tail(full options) PanelConnectivity.cs:530(12940) | high
328D_00 | wifiRSSI (dBm) | TT:238 PanelConnectivity.cs:517(12941) | high
328E_00 | wifiStatus 0=Not initialized 1=Running 2=Disabled 3=Error | TT:239 EDS tail PanelMonitoring.cs:514(12942) | high
328F_00 | wifiSupported WiFi hardware available (ro) | TT:240 PanelInformation.cs:325(0x328F00) | high
3291_00 | softAPEnabled AP enabled after boot (15 min) | TT:241 EDS tail PanelConnectivity.cs:532(12945) | high
3292_00 | softAPStart Start AP (bool) | TT:242 EDS tail PanelConnectivity.cs:533(12946) | high
3293_00 | wifiStationStatus 0=Not initialized 1=Not configured 2=Not connected 3=Connected | TT:243 EDS tail PanelConnectivity.cs:531(12947) PanelMonitoring.cs:515 | high
3294_00 | wifiAPStatus 0=Not initialized 1=Disabled 2=Enabled | TT:244 EDS tail PanelMonitoring.cs:518(12948) | high
3296_01 | commIPaddress4:Value AP IP | TT:245 PanelConnectivity.cs:544(12950,1) | high
3297_01 | commNetMask4:Value AP netmask | TT:246 PanelConnectivity.cs:545(12951,1) | high
3298_01 | commGWaddress4:Value AP gateway | TT:247 PanelConnectivity.cs:546(12952,1) | high
3299_01 | commDNS4_1:Value AP DNS1 | TT:248 PanelConnectivity.cs:547(12953,1) | high
3300_01 | commDNS4_2:Value AP DNS2 | TT:249 PanelConnectivity.cs:548(13056,1) | high
3550_00 | connectivityMode 0=None 1=Wired 2=Mobile 3=WiFi (ro) | TT:375 EDS tail | high
3553_00 | activeNetworkProfile 0=None 1..4=Profile 1..4 (ro) | TT:376 EDS tail PanelMonitoring.cs:509(13651) | high
3600_01 | ocpp_bootNotificationState 0=NOT_SENT 1=AWAITING_REPLY 2=REJECTED 3=ACCEPTED 4=PENDING (ro) | TT:374 PanelMonitoring.cs:505(13824,1) EBootNoticationStates.cs ICULanDevice.cs:2112 | high
4217_00 | sensOptionalEnergyMeter3 central meter protocol: -1=None 0=Serial Modbus 2=Serial FKN 3=Modbus TCP/IP 5=DSMR4.x/SMR5.0 | TT:43 EDS:1726 PanelPower.cs:312(16919) | high
4218_00 | sensEnergyMeterModbusType3 central Modbus brand (as 2218) | TT:44 EDS:1887 PanelPower.cs:398-399(16920) | high
4221_03..16 | meter3_* central meter values (layout as 2221) | TT:362-379 EDS 4221sub* | high
5217_00 | sensOptionalEnergyMeter4 smart meter Protocol Selection: 4=Modbus TCP/IP 5=DSMR4.x/SMR5.0(P1) 6=Modbus RTU 7=TIC (Linky) | TT:81 PanelLoadbalancing.cs:663(21015) EMeterTypes.cs | high
5218_00 | sensEnergyMeterModbusType4 smart meter brand: 0=Pulse 1=ABB 4=Saia 5=Carlo Gavazzi 7=IVU 8=DZG Reallin 9=Socomec 10=Custom 11=ABB EV3 12=EASTRON 13=Reallin 1P | TT:82 EDS:1764 PanelLoadbalancing.cs:874(21016) | high
5221_03..16 | meter4_* smart-meter values (layout as 2221) | TT:380-403 DlgSmartMeterTest.cs:50(21025) | high
5230_00 | registerMeterValueIncludePhases Send measured values incl phases | TT:227 PanelConnectivity.cs:627(21040) | high
8101_01 | socketBoard:deviceId (per node b) Device Id (ro) | PanelInformation.cs:361(33025,b) | medium
8102_01 | socketBoard:hardwareVersion (ro) | PanelInformation.cs:362(33026) | medium
8103_01 | socketBoard:softwareVersion (ro) | PanelInformation.cs:363(33027) | medium
8107_01 | socketBoard:iso15118Info (ro) | PanelInformation.cs:369(33031) | medium
8108_01 | socketBoard:energymeterInfo (ro) | PanelInformation.cs:368(33032) | medium
810A_01 | socketBoard:isDC1 DC flag ==1 → Ecog/DC variant | ICULanDevice.cs:369(33034,1; 33034,2) | medium
8400_01 | extensionBoardAssy tamper extension board assembly (ro) | PanelInformation.cs:388(33792,1) EDS tail | high
8401_01 | mainNormalMaxPower1 Max power (W) connector 1 | TT:38 MainWindow.cs:1795(33793,1) | high
8401_02 | mainNormalMaxPower2 Max power (W) connector 2 | TT:39 MainWindow.cs:1796(33793,2) | high
8402_01 | socketBoard:extendedSoftwareInfo (ro) | PanelInformation.cs:366(33794) | medium
82C1_00 | auxBoard:deviceId Auxiliary board Device Id (ro) | PanelInformation.cs:381(33537) | medium
82C2_00 | auxBoard:hardwareVersion (ro) | PanelInformation.cs:382(33538) | medium
82C3_00 | auxBoard:softwareVersion (ro) | PanelInformation.cs:383(33539) | medium
82D1_00 | fanFront:status0 Frontchamber fan status 0 (ro) | PanelMonitoring.cs:497(33553,0) | medium
82D2_00..02 | fanBack:status0..2 Backchamber fan status (ro) | PanelMonitoring.cs:499-501(33554) | medium
82E0_00 | tempSensors:P4 Exit temp backchamber (°C, ro) | PanelMonitoring.cs:479(33568,0) | high
82E0_01 | tempSensors:P5 DC fuse ambient temp (°C, ro) | PanelMonitoring.cs:475(33568,1) | high
82E0_02 | tempSensors:P6 DC+ relay temp (°C, ro) | PanelMonitoring.cs:476(33568,2) | high
82E0_03 | tempSensors:P7 Entrance temp backchamber (°C, ro) | PanelMonitoring.cs:480(33568,3) | high
82E0_04 | tempSensors:P8 12V auxiliary temp (°C, ro) | PanelMonitoring.cs:477(33568,4) | high

NOT FOUND in this source (report to Android/HA miners): 2065_00, 212E_00, 212F_00, 2219_00, 3251_00, 3253_00, 3260_01/03/04 (partial names), 3290_00, 3295_00. NOTE on assignment hypothesis: '2300-2331 socket capacity/current-limit presets' is WRONG — 2300-2336 are LED colour preset blocks (verified via EDS ParameterNames ledsState*); '2171-218F' is not a contiguous block — only the individually-listed 2171..2189 properties exist.

=== ENUM MAPS (value→label) ===
EMainStates (2501_01/2502_01, EMainStates.cs; order=value): -1=STATE_ILLEGAL, 0=STATE_UNKNOWN, 1=STATE_BOOTING, 2=STATE_AVAILABLE, 3=STATE_CABLE_CONNECTED, 4=STATE_CABLE_CONNECTED_TIMEOUT, 5=STATE_EV_CONNECTED, 6=STATE_BUTTON_ACTIVATED, 7=STATE_NFC_AVAILABLE, 8=STATE_NFC_AUTHORISED, 9=STATE_WAIT_FOR_EVCONNECT, 10=STATE_CHARGING_TEST_RELAYS, 11=STATE_CHARGING_POWER_OFF, 12=STATE_CHARGING_POWER_OFF_LOW_MAXCURRENT, 13=STATE_CHARGING_POWER_STARTING, 14=STATE_CHARGING_POWER_ON, 15=STATE_CHARGING_POWER_ON_SIMPLIFIED, 16=STATE_CHARGING_WAIT_FOR_EV_RECONNECT, 17=STATE_CHARGING_TERMINATING, 18=STATE_CHARGING_WAKEUP, 19=STATE_WAIT_FOR_DISCONNECT, 20=STATE_WAIT_FOR_RELEASE_AUTHORISATION, 21=STATE_CHARGING_RECOVER_FROM_OUTAGE, 22=STATE_ERROR, 23=STATE_ERROR_MESSAGE, 24=STATE_ERROR_MESSAGE_CABLE_NOT_SUPPORTED, 25=STATE_ERROR_ILLEGAL_MODE_3, 26=STATE_ERROR_TOO_MANY_RESTARTS, 27=STATE_ERROR_CHARGING, 28=STATE_ERROR_CHARGING_OVERCURRENT, 29=STATE_ERROR_CHARGING_HF_CONTACTOR_SWITCHING, 30=STATE_ERROR_S2_NOT_OPENED, 31=STATE_ERROR_PROTECTIVE_EARTH, 32=STATE_ERROR_RELAYS, 33=STATE_ERROR_LOW_SUPPLY_VOLTAGE, 34=STATE_ERROR_INTERNAL_VOLTAGE, 35=STATE_ERROR_POWERMETER, 36=STATE_ERROR_TEMPERATURE, 37=STATE_SUSPENDED, 38=STATE_INOPERATIVE, 39=STATE_RESERVED, 40=STATE_ERROR_CHARGING_RCD_SIGNALED, 41=STATE_CHARGING_POWER_OFF_VENTILATING, 42=STATE_CHARGING_POWER_OFF_SUSPENDED, 43=STATE_CHARGING_POWER_OFF_PHASE_CHANGE, 44=STATE_WAIT_FOR_START_METERVALUE, 45=STATE_WAIT_FOR_STOP_METERVALUE, 46=STATE_ERROR_SOCKET_MOTOR, 47=STATE_CABLE_CONNECTED_TYPE_E, 48=STATE_CABLE_CONNECTED_TIMEOUT_TYPE_E, 49=STATE_CHARGING_TYPE_E, 50=STATE_WAIT_FOR_DISCONNECT_TYPE_E, 51=STATE_CHARGING_SUSPENDED_TYPE_E, 52=STATE_CHARGING_LOW_MAXCURRENT_TYPE_E, 53=STATE_INVALID_CARD, 54=STATE_EV_CONNECTED_UNAUTHORIZED, 55=STATE_WAIT_FOR_DISCONNECT_PP
EMode3States (2501_04/2502_04, EMode3States.cs): 160=A0(0xA0) 161=A1 162=A2 177=B1 178=B2 193=C1 194=C2 209=D1 210=D2 224=E 240=F
ELEDStates (2501_02/2502_02, ELEDStates.cs): 0=LED_UNKNOWN 1=LED_OFF 2=LED_BOOTING 3=LED_BOOTING_CHECK_MAINS 4=LED_AVAILABLE 5=LED_PREP_AUTHORIZING 6=LED_PREP_AUTHORIZED 7=LED_PREP_CABLE_CONNECTED 8=LED_PREP_EV_CONNECTED 9=LED_CHARGING_PREPARING 10=LED_CHARGING_WAIT_VEHICLE 11=LED_CHARGING_ACTIVE_NORMAL 12=LED_CHARGING_ACTIVE_SIMPLIFIED 13=LED_CHARGING_SUSPENDED_OVERCURRENT 14=LED_CHARGING_SUSPENDED_HF_SWITCHING 15=LED_CHARGING_SUSPENDED_EV_DISCONNECTED 16=LED_FINISH_WAIT_VEHICLE 17=LED_FINISH_WAIT_FOR_DISCONNECT 18=LED_ERROR_PROTECTIVE_EARTH 19=LED_ERROR_POWERLINE_FAULT 20=LED_ERROR_CONTACTOR_FAULT 21=LED_ERROR_CHARGING 22=LED_ERROR_POWERFAILURE 23=LED_ERROR_TEMPERATURE 24=LED_ERROR_ILLEGAL_CP_VALUE 25=LED_ERROR_ILLEGAL_PP_VALUE 26=LED_ERROR 27=LED_ERROR_TOO_MANY_RESTARTS 28=LED_ERRORMESSAGE 29=LED_ERRORMESSAGE_NOT_AUTHORIZED 30=LED_ERRORMESSAGE_CABLE_NOT_SUPPORTED 31=LED_ERRORMESSAGE_S2_NOT_OPENED 32=LED_ERRORMESSAGE_TIMEOUT 33=LED_RESERVED 34=LED_INOPERATIVE 35=LED_LOADBALANCING_LIMITED 36=LED_LOADBALANCING_FORCED_OFF 37=LED_TAG_MODE 38=LED_TAG_MODE_ADDED 39=LED_TAG_MODE_REMOVED 40=LED_CHARGING_NON_CHARGING
ESocketStates (2501_03 fw<7.3, ESocketStates.cs): -1=POWER_RELAYS_UNKNOWN 0=POWER_MAIN_OFF_BYPASS_OFF 1=POWER_MAIN_ON_BYPASS_OFF 2=POWER_MAIN_ON_BYPASS_ON 3=POWER_MAIN_ON_TRIAC_ON; fw>=7.3: 0=OFF 1=ON (ESocketPowerStates)
EUserInterfaceStates (3190_01/3191_01, EUserInterfaceStates.cs): 0=UNKNOWN 1=BOOTING 2=AVAILABLE 3=CABLE_CONNECTED 4=EV_CONNECTED 5=CABLE_AUTHORISED 6=AUTHORISED 7=COMMUNICATING 8=POWER_OFF_LOW_MAX_CURRENT 9=POWER_OFF_SUSPENDED 10=CHARGING 11=CHARGING_FULL_LOCKED 12=CHARGING_FULL_UNLOCKED 13=WAIT_FOR_EV_RECONNECT 14=TRANSACTION_INFO 15=CARD_REJECTED 16=ERROR 17=PLEASEWAIT 18=RESERVED 19=QRCODE 20=WARNING 21=WAIT_FOR_RELEASE 22=PLEASE_REMOVE_CABLE 23=PLEASEWAIT_EV_COMM 24=WAIT_FOR_RELEASE_PC 25=INVALID_CARD
EAHWPCSMMainStates (2501_01 AHP, EAHWPCSMMainStates.cs): 0=Unknown 1=Available 2=Authorising 4=Authorised 8=Rejected 15=Booting 16=CableConnected 18=CableConnectedAuthorising 20=CableConnectedAuthorised 24=CableConnectedRejected 48=EVConnected 50=EVConnectedAuthorising 52=EVConnectedAuthorised 56=EVConnectedRejected 65=CableLocked 66=ChargingStarting 67=Charging 68=ChargingFinishing 69=ChargingFinished 70=CableUnlock 71=SuspendedEV 72=SuspendedEVSE 73=ChargingEVFull 74=ChargeParameterDiscovery 75=CableCheck 76=PreCharge 79=WaitForCableDisconnect 128..132=TimeoutWaiting* (Cable/EVConnect/Authorisation/S2/CableRemoval) 159=Offline 160=Inoperative 161=Reserved 162=TariffAndOrTimeChanged 192=ErrorMask 193..212=ErrorRelay,ErrorTemperatureHigh,ErrorOvercurrent,ErrorSocketMotor,ErrorIllegalMode3CP,ErrorEnergyMeter,ErrorPhase,ErrorInternalRCDTripped,ErrorHFSwitching,ErrorLowSupplyVoltage,ErrorExternalRCD,ErrorGeneric,ErrorTamper,ErrorComponent,ErrorInternalVoltage,ErrorIllegalMode3PP,ErrorRelayOrRCD,ErrorSocketMotorBoot,ErrorTemperatureLow,ErrorInternalRCDFailure 224=ErrorSCBMask 225..229=ErrorStationError,ErrorMissingRFID,ErrorMissingPnCID,ErrorMissingSignedMeter,ErrorMissingTariffs
EAHWPCCStates (2501_05): 0=unknown 1=init 2=idle 3=waitForStartMV 4=preparing 5=waitForEVConnect 6=chargingPowerOn 7=chargingPowerOff 8=chargingWaitForEVReconnect 9=switchPhases 10=waitForStopMV 11=finished 12=lowSupplyVoltageError 13=recoverFromOutage 14=relayError 15=chargingSuspendedEVSE 16=temperatureError 17=overcurrentError 18=socketMotorError 19=illegalMode3Error 20=energyMeterError 21=phaseError 22=internalRCDError 23=hfSwitchingError 24=stopRequested 25=stationError 26=chargeParameterDiscovery 27=cableCheck 28=preCharge 29=genericError 30=tamperError 31=componentError 32=InternalVoltageError 33=IllegalMode3PPError 34=SocketMotorBootError 35=TemperatureLowError 36=InternalRCDTrippedError 37=stateCount
EAHWPCPROStates (2501_03 AHP): 0=UNKNOWN 1=INACTIVE 2=CONNECTED_ISO15118_PWM 3=WAIT_FOR_EV_CONNECT 4=EV_CONNECTED 5=ACTIVE 6=WAIT_FOR_S2_CLOSE 7=WAIT_FOR_S2_OPEN 8=SUSPENDED 9=VENTILATING 10=WAKEUP_STATE_E 11=WAKEUP_STATE_B1 12=ERROR 13=ERROR_EV_DETECT 14=WAIT_FOR_EV_DISCONNECT 15=PREPARED 16=CONNECTED_ISO15118_ERROR 17=CONNECTED_ISO15118_X1 18=CHECK_RELAYS 19=COUNT
EBootNoticationStates (3600_01): 0=NOT_SENT 1=AWAITING_REPLY 2=REJECTED 3=ACCEPTED 4=PENDING
EModbusTCPIPConnectionStates (2540_00): 0=COMMUNICATION_IDLE 1=COMMUNICATION_INITIALIZING 2=COMMUNICATION_NORMAL 3=COMMUNICATION_WARNING 4=COMMUNICATION_ERROR
ETamperState (2250_00): 0=Unknown 1=Not_Tampered 2=TamperActive 3=Tampered 4=Tampered_Ack
EGiroEState (2188_00): 0=DISABLED 1=ENABLED 2=OFFLINE
EDirectPaymentOptions (2192_00, flags): 0=None 1=OTS 2=QRCode 4=GiroE
EAuthorisationMethod (2126_00): 0=Plug&Charge 1=RFID 2=Backoffice/CommUnit 3=Button
EOfflineAuthorisationMethod (2127_00+213E_00 combined): 0=OFFLINE_REFUSE_ALL 1=OFFLINE_ACCEPT_KNOWN 3=OFFLINE_ACCEPT_ALL
EMeterTypes (4217/5217): -1=NONE 0=MODBUS_CENTRAL 2=FKN 3=TCPIP_CENTRAL 4=TCPIP_SMART 5=P1/DSMR 6=RTU_SMART 7=TIC
EAlbConfiguration (ICULanDevice.cs:596-614): 5217 value 4→TCP(EMS if 2530_01==3, Socomec if 2523_02==1, else Custom), 5→P1(2191_01: 0=Serial 1=Telnet 2=HomeWizard), 6→RTU, 7→TIC/Linky
ERadioAccessTechnology: 1=GPRS 2=UMTS 4=LTE
Security profile (2723_00 / 20F0_05): 0='0: Default' 1='1: Unsecure transport with Basic Authentication' 2='2: TLS with Basic Authentication' 3='3: TLS with Client Side Certificates' (PanelConnectivity.cs:273-276)
StatusNotification method (209C_00): 0=Immediate/Normal 1=Immediate timestamp 2=Queued (PanelConnectivity.cs:265-267)
Meter value transmission (2088_00): 0=End 1=During 2=Always (:268-270); alignment (2089_00): 0=Boot 1=Clock (:271-272)
SCN PhaseMapping (2180_07/09): 0=None 1=L1 2=L2 3=L3 4=L1L2L3 5=L1L3L2 6=L2L1L3 7=L2L3L1 8=L3L1L2 9=L3L2L1
OCPP measurand values (2098_xx/2099_xx, EOcppMeasurand.cs + PanelConnectivity.cs:277-362): 0=None 1=Energy.Active.Export.Register 2=Energy.Active.Import.Register 3=Energy.Reactive.Export.Register 4=Energy.Reactive.Import.Register 5=Energy.Active.Export.Interval 6=Energy.Active.Import.Interval 7=Energy.Reactive.Export.Interval 8=Energy.Reactive.Import.Interval 9=Power.Active.Export 10=Power.Active.Import 11=Power.Reactive.Export 12=Power.Reactive.Import 13=Current.Export 14=Current.Import 15=Voltage 16=Temperature 17=Current.L1 18=Current.L2 19=Current.L3 20=Current.Maximum 21=Power.Factor 22=Current.Offered 23=Power.Offered 24=Frequency 25=RPM 26=SoC 29=Energy.Active.Net 30=Energy.Reactive.Net 31=Energy.Apparent.Net 32=Energy.Apparent.Import 33=Energy.Apparent.Export; phase component in high 16 bits: 1=L1-N 2=L2-N 3=L3-N 4=L1-L2 5=L2-L3 6=L3-L1 7=N 8=L1 9=L2 10=L3 (OccpPhases)
Tamper detection mode (2251_02): 0=Disabled 1=Strict 2=Authorization
Solar charging (3280_01): 0=Off 1=Comfort 2=Green
Firmware update status (2911_00): see table entry
Master tag mode (2400_01): 0=Disabled 1=Enabled
NP priority (20F0_0E): 0=Not used 1..4; NP interface (20F0_06): 0=None 1-4=Wired(Ethernet) 5=Mobile 6=WiFi (ENPInterface PanelConnectivity.cs:35-46)
Connector types (2125/3125): 0=Fixed Cable 1=Balz/Mennekes 2=FCT 3=Schuko 4=Fixed cable type 1 5=Fixed cable type 2 6=Fixed cable CCS 7=Fixed cable ChaDeMo (EDS:927-982)
204F_00 config bitmask: phases bits0-1: 0='1F' 2='3F'; cable bits4-5(0x30): 0='Fixed cable type 1' 16='Fixed cable type 2' 32='Fixed cable type 3' 48='Socket'; 0x80=Type-E second outlet (PanelSockets.cs:12-21,43-45; PanelPower.cs:266,288)
TariffDisplayOptionsType (3262_05): 1=disclaimer 2=perKwh 4=perMinute 8=perSession 16=perOther 32=adhocOnlyDisclaimer (TariffDisplayOptionsType.cs)

=== UNITS ===
A: 2062 2067 2068 206A 2128 2129 212A 212B 212C 212D 2130 2173 2174_02 2180_05 2180_06 2180_0A 3129 3173 | s: 206B_02 2086 2087 2089? 208A 208B 208D 208E 208F 2097 209A 2124? 2131 2135 2136 2156 2181 2182 2184 2185 2191_03 2180_04 2204 2205 2216 3258 2530_04 | msec/ms: 2139 2140 2142-2154 215A | °C: 2201 2202 2203 2249_00 2249_01 82E0_xx | V: 2221_03..08 3221/4221/5221 same subs 2224 2225 2228 2229 2511_00 2511_01 2512_00 2511_01 | A: 2221_09..0C 2511_02 2512_02 | Ω: 2231 2233 2247_03 2511_02 | Hz: 2221_12 | W: 206B_03 21B9? 3280_03 | kW: 2221_13..16 | kWh: 2221_22 2221_26 | %: 2061_02 2172 3280_02 | dBm: 2110 2111 328D | sec (epoch): 2221_01

=== TYPE HINTS (from EDS + code) ===
string: 2050 2051 2053 2055 2057 205D 2069 2076 2081 2082 2083 2100-2105 2112 2115 2116_00 2118-2121 213A 216E 2177 2178 2180_01 2191_02 2522_04 2523_04 2575_02 328A 328B 3262_01/07 82C1-82C3 8101/8102/8103/8107/8108/8402 | u8/bool: most checkboxes (2061_01 2064 206A? no 206F 2070 207D_02 2093-209D 2127? 213B 213C 213D 2159 215D 215E 216A 216B 216F 2183 2185 2188? 2190 21B0 21B2 21B4 2206 2251_01 23xx LEDs 2400_01 3284 3291 3292 3294 5230) | i16: 205A 205B 2061_01 2061_02 2126 2127 2128? no 2131? 2135-2137? (2137 u16) 2207-2209? (i16) 2210-2216 | u16: 2084? 2087 2138? 2145-2154 2145+ 2153 2154 2190? 2206? 328D? | u32: 2056 205F_00 2066 209E 209F? 2109? 2189 2180? 2610? 2915 328C | REAL32: 205C_01/02 2062 2067 2068 206A 2128-2130 212A-212D 2180_05/06/0A 2201-2203 2221_03+ 5221_03+ 2249_00/01 82E0_xx | epoch64 (0x001B): 2059 2187 21B3 8273? 8627 8583 8281 | bytearray (0x000F): 2700 2701 2903 2912 2913 2914 2560-2573 regmaps

=== MULTI-SUB OBJECT LAYOUTS ===
2221/3221/4221/5221 (meterN): 1=TimeStamp 3=V L1N 4=V L2N 5=V L3N 6=V L1L2 7=V L2L3 8=V L3L1 9=I N 10(0A)=I L1 11(0B)=I L2 12(0C)=I L3 14(0E)=cosφL1 15(0F)=cosφL2 16(10)=cosφL3 17(11)=cosφSum 18(12)=Frequency 19(13)=P L1 20(14)=P L2 21(15)=P L3 22(16)=P Sum 34(22)=EnergyDeliveredSum 38(26)=EnergyConsumedSum
20F0-20F3 (network profile N): 1=OCPP version 3=CSMS URL 4=websocket timeout 5=security profile 6=connect method 7=APN name 8|15=APN user 9=APN password 10|16=SIM pin 14=priority (8/15/16 only when extended field lengths, i.e. 20F0_0F exists)
2300-2336 (LED state): 1=red1 2=green1 3=blue1 4=cyan1 5=duration1 6=red2 7=green2 8=blue2 9=cyan2 10(0A)=duration2
2522/2523 (MbusTCP central/external): 1=enabled 2=SlaveType 3=ConnectionType 4=IP 6=SlaveAddress
2530 (modbusTCPIPSlave EMS): 1=options/data source 3=SCN enable/mode 4=validity time
2574 (modbusSmartMeterConfig): 0=wordOrder 1=updateTime 2=readTimeout 3=functionCode; 2575 (uart): 0=baudrate 1=parity 2=address
3262 (displayPricing): 1=currency 2=startPrice 3=energyPrice 4=minutePrice 5=showPriceComponent flags 6=otherPrice 7=otherSpecifier
3280 (solarCharging): 1=mode 2=greenShare 3=comfortLevel 4=boost socket1 5=boost socket2
3285-3289/3296-3300 (IP3 WiFi / IP4 AP): sub1=value sub2=isFixed (204F-style _01/_02 pairs; 2073/2074/2075/207D families follow same :Value/:isFixed pattern)
2180 (SCN): see table
2170 (mainRequest): 3=LocalDBRequest 4=ResetRequest

=== WRITE-ONLY / SPECIAL ACCESS ===
Write-only: 2100 2101 2102 2103 (APN/SIM), 2116_01 ProxyPassword, 2701 PreSharedKey, 2723_01 BackOfficeAuthorizationKey, 2912 firmware upload, 328B wifiPSK (SetProperty 12939 never read). Read-only: 1008 1009 100A 2052 2054 2056 2057 2059(rww=write to sync) 2086 209E 209F 2104 2105 2110 2111 2112 2118-2121 213A 2217 2221_* meter subs 2249 2251_01 2501_01..05 2502_* 2511_* 2512_* 2540 2541 2542 312E 312F 3180-3182 3190_01 3191_01 3221_* 3550 3553 3600_01 4217 4221_* 5221_* 8101-810A 82C1-82E0 8400. One-way/locked: 216A Eichrecht (disable blocked), 2051 serial (AllowObjectIDUpdate guard), 2052/2075/207D MAC/IP fix flags. Time sync: 2059 rww — installer writes epoch ms (ICULanDevice.cs:2604-2607); 8281=2059 alt key used by SetDate.

## Evidence legend
* `TT:N` — `tooltip_en_GB.csv` line N (shipped in app/ inside the MSI's cab).
* `EDS:N` — `EDS.xml` line N (shipped beside the exe).
* `CFG:N` — `config.json` feature entry N: the decrypted `InstallerConfigV3.dat`
  (`PasswordDeriveBytes("Pas5pR@sE", "s@1tVaLue", "SHA1", 2)` key, IV
  `@1B2c3D4e5F6g7H8`; see windows-guide.md step 4).
* `Panel*.cs:line` / `ICULanDevice.cs:line` etc. — decompiled C# (ilspycmd)
  from the installer's .NET assemblies.
