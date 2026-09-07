# My Eve (Alfen Android app v2.3.1) — property findings

How these were obtained (unpack, decompile, mine): `android-guide.md` in
this directory.

Source: `MyEve+-+Alfen_2.3.1_APKPure.xapk` → `com.alfen.myeve.apk` →
`assets/index.android.bundle` (Hermes bytecode v96), decompiled with
hermes-dec 0.1.7 to a single ~38 MB `decompiled.js` (not committed; any run
of the guide reproduces it). Evidence offsets refer to that file.

**KEY FORMATTING NOTE:** the app writes subIds zero-padded to 2 hex digits (`2051_00`, `205C_01`).
Below they are normalized to alfenctl's format (`2051_0`, `205C_1`). propId is hex without 0x.

The app embeds a complete `id -> display name` dictionary (745 entries, English) as a JS object literal
at decompiled.js byte offsets ~37665770–37671200 (single line, so offsets are given instead of line numbers;
line for the whole dict region: `grep -n "'2056_00': 'Number of bootups'"` region is one line — use offsets).
745/745 ids have exactly one name each. 305 of the 311 live NG910 (fw 7.4.5) properties are covered.
Live ids NOT present in the app: 2522_5, 2523_5, 3251_0, 3253_0, 3292_0, 3295_0.

## Property table (id | name | evidence | confidence)

Evidence: `decompiled.js@<byte offset>` — offset of the `'ID': 'Name'` pair inside the embedded name dictionary.

1008_0 | Platform Type | decompiled.js@37665770 (dict '1008_00': 'Platform Type') | high
1009_0 | Manufacturer Hardware Version | decompiled.js@37665798 (dict '1009_00': 'Manufacturer Hardware Version') | high
100A_0 | Manufacturer Software Version | decompiled.js@37665842 (dict '100A_00': 'Manufacturer Software Version') | high
2005_0 | Protocol Version | decompiled.js@37665886 (dict '2005_00': 'Protocol Version') | high
204D_1 | Hardware version controler board | decompiled.js@37665917 (dict '204D_01': 'Hardware version controler board') | high
204D_2 | Hardware assembly controler board | decompiled.js@37665964 (dict '204D_02': 'Hardware assembly controler board') | high
204D_3 | Hardware version power board | decompiled.js@37666012 (dict '204D_03': 'Hardware version power board') | high
204D_4 | Hardware assembly power board | decompiled.js@37666055 (dict '204D_04': 'Hardware assembly power board') | high
204F_0 | Charging Station Configurartion | decompiled.js@37666099 (dict '204F_00': 'Charging Station Configurartion') | high
2050_0 | Model | decompiled.js@37666145 (dict '2050_00': 'Model') | high
2051_0 | Object number | decompiled.js@37666165 (dict '2051_00': 'Object number') | high
2052_1 | Ethernet MAC address | decompiled.js@37666193 (dict '2052_01': 'Ethernet MAC address') | high
2052_2 | Fixed Ethernet MAC address | decompiled.js@37666228 (dict '2052_02': 'Fixed Ethernet MAC address') | high
2053_0 | Customer Ident. number | decompiled.js@37666269 (dict '2053_00': 'Customer Ident. number') | high
2054_0 | Firmrware version | decompiled.js@37666306 (dict '2054_00': 'Firmrware version') | high
2055_0 | Charge point vendor | decompiled.js@37666338 (dict '2055_00': 'Charge point vendor') | high
2056_0 | Number of bootups | decompiled.js@37666372 (dict '2056_00': 'Number of bootups') | high
2057_0 | Boot Reason | decompiled.js@37666404 (dict '2057_00': 'Boot Reason') | high
2059_0 | Charge date and time | decompiled.js@37666430 (dict '2059_00': 'Charge date and time') | high
205B_0 | Daylight savings | decompiled.js@37666465 (dict '205B_00': 'Daylight savings') | high
205C_1 | Latitude | decompiled.js@37666496 (dict '205C_01': 'Latitude') | high
205C_2 | Longitude | decompiled.js@37666519 (dict '205C_02': 'Longitude') | high
205D_0 | Display language | decompiled.js@37666543 (dict '205D_00': 'Display language') | high
205E_0 | Number of Sockets | decompiled.js@37666574 (dict '205E_00': 'Number of Sockets') | high
205F_0 | Socket 1 - Status | decompiled.js@37666606 (dict '205F_00': 'Socket 1 - Status') | high
2060_0 | System uptime | decompiled.js@37666638 (dict '2060_00': 'System uptime') | high
2061_1 | Auto-adjust brightness mode | decompiled.js@37666666 (dict '2061_01': 'Auto-adjust brightness mode') | high
2061_2 | Display & LED Brightness | decompiled.js@37666708 (dict '2061_02': 'Display & LED Brightness') | high
2062_0 | Station maximum current (A) | decompiled.js@37666747 (dict '2062_00': 'Station maximum current (A)') | high
2063_0 | Plug and Charge Identification | decompiled.js@37666789 (dict '2063_00': 'Plug and Charge Identification') | high
2064_0 | Load balancing mode | decompiled.js@37666834 (dict '2064_00': 'Load balancing mode') | high
2065_1 | Smart Charging Mode Enabled | decompiled.js@37666868 (dict '2065_01': 'Smart Charging Mode Enabled') | high
2066_0 | Active LB - Status Flags | decompiled.js@37666910 (dict '2066_00': 'Active LB - Status Flags') | high
2067_0 | Maximum smart meter current (A) | decompiled.js@37666949 (dict '2067_00': 'Maximum smart meter current (A)') | high
2068_0 | Active LB - Safe current (A) | decompiled.js@37666995 (dict '2068_00': 'Active LB - Safe current (A)') | high
2068_1 | Socket 1 - Safe Current (A) | decompiled.js@37667038 (dict '2068_01': 'Socket 1 - Safe Current (A)') | high
2068_2 | Socket 2 - Safe Current (A) | decompiled.js@37667080 (dict '2068_02': 'Socket 2 - Safe Current (A)') | high
2069_0 | Active LB - Phase rotation | decompiled.js@37667122 (dict '2069_00': 'Active LB - Phase rotation') | high
206A_0 | Minimum Chameleon current (A) | decompiled.js@37667163 (dict '206A_00': 'Minimum Chameleon current (A)') | high
206B_1 | Nuvve Support - Active | decompiled.js@37667207 (dict '206B_01': 'Nuvve Support - Active') | high
206B_2 | Nuvve Support - Interval (s) | decompiled.js@37667244 (dict '206B_02': 'Nuvve Support - Interval (s)') | high
206B_3 | Nuvve Support - Threshold (W) | decompiled.js@37667287 (dict '206B_03': 'Nuvve Support - Threshold (W)') | high
206C_1 | OCPP 1.5 Smart Charging | decompiled.js@37667331 (dict '206C_01': 'OCPP 1.5 Smart Charging') | high
206E_0 | Time zone | decompiled.js@37667369 (dict '206E_00': 'Time zone') | high
206F_0 | Received measurements | decompiled.js@37667393 (dict '206F_00': 'Received measurements') | high
2070_0 | 6mA Detect response | decompiled.js@37667429 (dict '2070_00': '6mA Detect response') | high
2071_1 | Ethernet - Back Office URL | decompiled.js@37667463 (dict '2071_01': 'Ethernet - Back Office URL') | high
2071_2 | Ethernet - Back Office Path | decompiled.js@37667504 (dict '2071_02': 'Ethernet - Back Office Path') | high
2072_1 | Mobile - DHCP Address | decompiled.js@37667546 (dict '2072_01': 'Mobile - DHCP Address') | high
2072_2 | Mobile - Fixed DHCP | decompiled.js@37667582 (dict '2072_02': 'Mobile - Fixed DHCP') | high
2073_1 | Mobile - Netmask | decompiled.js@37667616 (dict '2073_01': 'Mobile - Netmask') | high
2074_1 | Mobile - Gateway address | decompiled.js@37667647 (dict '2074_01': 'Mobile - Gateway address') | high
2075_1 | Mobile - IP address | decompiled.js@37667686 (dict '2075_01': 'Mobile - IP address') | high
2075_2 | Mobile - Fixed IP address | decompiled.js@37667720 (dict '2075_02': 'Mobile - Fixed IP address') | high
2076_0 | Backoffice & Modbus preset | decompiled.js@37667760 (dict '2076_00': 'Backoffice & Modbus preset') | high
2077_0 | Backoffice Connect method | decompiled.js@37667801 (dict '2077_00': 'Backoffice Connect method') | high
2078_1 | Mobile - Back Office URL | decompiled.js@37667841 (dict '2078_01': 'Mobile - Back Office URL') | high
2078_2 | Mobile - Back Office Path | decompiled.js@37667880 (dict '2078_02': 'Mobile - Back Office Path') | high
2079_1 | Mobile - DNS address 1 | decompiled.js@37667920 (dict '2079_01': 'Mobile - DNS address 1') | high
2079_2 | Mobile - Fixed DNS 1 | decompiled.js@37667957 (dict '2079_02': 'Mobile - Fixed DNS 1') | high
207A_1 | Ethernet - DHCP address | decompiled.js@37667992 (dict '207A_01': 'Ethernet - DHCP address') | high
207A_2 | Ethernet - Fixed DHCP | decompiled.js@37668030 (dict '207A_02': 'Ethernet - Fixed DHCP') | high
207B_1 | Ethernet - Netmask | decompiled.js@37668066 (dict '207B_01': 'Ethernet - Netmask') | high
207C_1 | Ethernet - Gateway address | decompiled.js@37668099 (dict '207C_01': 'Ethernet - Gateway address') | high
207D_1 | Ethernet - IP address | decompiled.js@37668140 (dict '207D_01': 'Ethernet - IP address') | high
207D_2 | Ethernet - Fixed IP address | decompiled.js@37668176 (dict '207D_02': 'Ethernet - Fixed IP address') | high
207E_1 | Ethernet - DNS address 1 | decompiled.js@37668218 (dict '207E_01': 'Ethernet - DNS address 1') | high
207E_2 | Ethernet - Fixed DNS 1 | decompiled.js@37668257 (dict '207E_02': 'Ethernet - Fixed DNS 1') | high
207F_1 | Ethernet - DNS address 2 | decompiled.js@37668294 (dict '207F_01': 'Ethernet - DNS address 2') | high
207F_2 | Ethernet - Fixed DNS 2 | decompiled.js@37668333 (dict '207F_02': 'Ethernet - Fixed DNS 2') | high
2080_1 | Mobile - DNS address 2 | decompiled.js@37668370 (dict '2080_01': 'Mobile - DNS address 2') | high
2080_2 | Mobile - Fixed DNS 2 | decompiled.js@37668407 (dict '2080_02': 'Mobile - Fixed DNS 2') | high
2081_0 | BO - Protocol Name | decompiled.js@37668442 (dict '2081_00': 'BO - Protocol Name') | high
2082_0 | BO - Protocol version | decompiled.js@37668475 (dict '2082_00': 'BO - Protocol version') | high
2086_0 | HeartBeat Interval (s) | decompiled.js@37668511 (dict '2086_00': 'HeartBeat Interval (s)') | high
2087_0 | Meter value sample interval (s) | decompiled.js@37668548 (dict '2087_00': 'Meter value sample interval (s)') | high
2088_0 | Meter value transmission mode | decompiled.js@37668594 (dict '2088_00': 'Meter value transmission mode') | high
2089_0 | Meter value alignment | decompiled.js@37668638 (dict '2089_00': 'Meter value alignment') | high
208A_0 | Ping pong interval (s) | decompiled.js@37668674 (dict '208A_00': 'Ping pong interval (s)') | high
208B_1 | Ethernet - websocket timeout (s) | decompiled.js@37668711 (dict '208B_01': 'Ethernet - websocket timeout (s)') | high
208B_2 | Wired - Websocket timeout (s) | decompiled.js@37668758 (dict '208B_02': 'Wired - Websocket timeout (s)') | high
208D_1 | Ethernet - OCPP send timeout (s) | decompiled.js@37668802 (dict '208D_01': 'Ethernet - OCPP send timeout (s)') | high
208D_2 | Mobile - OCCP send timeout (s) | decompiled.js@37668849 (dict '208D_02': 'Mobile - OCCP send timeout (s)') | high
208E_1 | Ethenet - OCPP reply timeout (s) | decompiled.js@37668894 (dict '208E_01': 'Ethenet - OCPP reply timeout (s)') | high
208E_2 | Mobile - OCPP reply timeout (s) | decompiled.js@37668941 (dict '208E_02': 'Mobile - OCPP reply timeout (s)') | high
208F_0 | Meter value sample interval (s) | decompiled.js@37668987 (dict '208F_00': 'Meter value sample interval (s)') | high
2093_0 | Send station status | decompiled.js@37669033 (dict '2093_00': 'Send station status') | high
2094_0 | Abort concurrent transaction | decompiled.js@37669067 (dict '2094_00': 'Abort concurrent transaction') | high
2095_0 | Stop transaction on invalid tag | decompiled.js@37669110 (dict '2095_00': 'Stop transaction on invalid tag') | high
2096_0 | Message attemps | decompiled.js@37669156 (dict '2096_00': 'Message attemps') | high
2097_0 | Message retry interval (s) | decompiled.js@37669186 (dict '2097_00': 'Message retry interval (s)') | high
2098_0 | Meter values sampled data - Data 0 | decompiled.js@37669227 (dict '2098_00': 'Meter values sampled data - Data 0') | high
2098_1 | Meter values sampled data - Data 1 | decompiled.js@37669276 (dict '2098_01': 'Meter values sampled data - Data 1') | high
2098_2 | Meter values sampled data - Data 2 | decompiled.js@37669325 (dict '2098_02': 'Meter values sampled data - Data 2') | high
2098_3 | Meter values sampled data - Data 3 | decompiled.js@37669374 (dict '2098_03': 'Meter values sampled data - Data 3') | high
2098_4 | Meter values sampled data - Data 4 | decompiled.js@37669423 (dict '2098_04': 'Meter values sampled data - Data 4') | high
2098_5 | Meter values sampled data - Data 5 | decompiled.js@37669472 (dict '2098_05': 'Meter values sampled data - Data 5') | high
2098_6 | Meter values sampled data - Data 6 | decompiled.js@37669521 (dict '2098_06': 'Meter values sampled data - Data 6') | high
2098_7 | Meter values sampled data - Data 7 | decompiled.js@37669570 (dict '2098_07': 'Meter values sampled data - Data 7') | high
2098_8 | Meter values sampled data - Data 8 | decompiled.js@37669619 (dict '2098_08': 'Meter values sampled data - Data 8') | high
2098_9 | Meter values sampled data - Data 9 | decompiled.js@37669668 (dict '2098_09': 'Meter values sampled data - Data 9') | high
2099_0 | Meter values aligned data - Data 0 | decompiled.js@37669717 (dict '2099_00': 'Meter values aligned data - Data 0') | high
2099_1 | Meter values algined data - Data 1 | decompiled.js@37669766 (dict '2099_01': 'Meter values algined data - Data 1') | high
2099_2 | Meter values algined data - Data 2 | decompiled.js@37669815 (dict '2099_02': 'Meter values algined data - Data 2') | high
2099_3 | Meter values algined data - Data 3 | decompiled.js@37669864 (dict '2099_03': 'Meter values algined data - Data 3') | high
2099_4 | Meter values algined data - Data 4 | decompiled.js@37669913 (dict '2099_04': 'Meter values algined data - Data 4') | high
2099_5 | Meter values algined data - Data 5 | decompiled.js@37669962 (dict '2099_05': 'Meter values algined data - Data 5') | high
2099_6 | Meter values algined data - Data 6 | decompiled.js@37670011 (dict '2099_06': 'Meter values algined data - Data 6') | high
2099_7 | Meter values algined data - Data 7 | decompiled.js@37670060 (dict '2099_07': 'Meter values algined data - Data 7') | high
2099_8 | Meter values algined data - Data 8 | decompiled.js@37670109 (dict '2099_08': 'Meter values algined data - Data 8') | high
2099_9 | Meter values algined data - Data 9 | decompiled.js@37670158 (dict '2099_09': 'Meter values algined data - Data 9') | high
209A_0 | Clock aligned data interval (s) | decompiled.js@37670207 (dict '209A_00': 'Clock aligned data interval (s)') | high
209B_0 | Remote transaction requests | decompiled.js@37670253 (dict '209B_00': 'Remote transaction requests') | high
209C_0 | Mode | decompiled.js@37670295 (dict '209C_00': 'Mode') | high
209D_0 | Send always | decompiled.js@37670314 (dict '209D_00': 'Send always') | high
209E_0 | Mobile - supported RATs | decompiled.js@37670340 (dict '209E_00': 'Mobile - supported RATs') | high
209F_0 | Mobile - actual RAT | decompiled.js@37670378 (dict '209F_00': 'Mobile - actual RAT') | high
20F0_1 | Network Profile 1 - BO Version | decompiled.js@37670412 (dict '20F0_01': 'Network Profile 1 - BO Version') | high
20F0_3 | Network Profile 1 - BO URL | decompiled.js@37670457 (dict '20F0_03': 'Network Profile 1 - BO URL') | high
20F0_4 | Network Profile 1 - Message Timeout (s) | decompiled.js@37670498 (dict '20F0_04': 'Network Profile 1 - Message Timeout (s)') | high
20F0_5 | Network Profile 1 - Security Profile | decompiled.js@37670552 (dict '20F0_05': 'Network Profile 1 - Security Profile') | high
20F0_6 | Network Profile 1 - BO Profile | decompiled.js@37670603 (dict '20F0_06': 'Network Profile 1 - BO Profile') | high
20F0_7 | Network Profile 1 - APN Username (deprecated) | decompiled.js@37670648 (dict '20F0_07': 'Network Profile 1 - APN Username (deprecated)') | high
20F0_8 | Network Profile 1 - APN Username | decompiled.js@37670708 (dict '20F0_08': 'Network Profile 1 - APN Username') | high
20F0_9 | Network Profile 1 - APN Password | decompiled.js@37670755 (dict '20F0_09': 'Network Profile 1 - APN Password') | high
20F0_A | Network Profile 1 - SIM PIN (deprecated) | decompiled.js@37670802 (dict '20F0_0A': 'Network Profile 1 - SIM PIN (deprecated)') | high
20F0_B | Network Profile 1 - Preferred Network | decompiled.js@37670857 (dict '20F0_0B': 'Network Profile 1 - Preferred Network') | high
20F0_C | Network Profile 1 - Use Preferred Only | decompiled.js@37670909 (dict '20F0_0C': 'Network Profile 1 - Use Preferred Only') | high
20F0_D | Network Profile 1 - APN Authentication | decompiled.js@37670962 (dict '20F0_0D': 'Network Profile 1 - APN Authentication') | high
20F0_E | Network Profile 1 - Priority | decompiled.js@37671015 (dict '20F0_0E': 'Network Profile 1 - Priority') | high
20F0_F | Network Profile 1 - APN Name | decompiled.js@37671058 (dict '20F0_0F': 'Network Profile 1 - APN Name') | high
20F0_10 | Network Profile 1 - SIM PIN | decompiled.js@37671101 (dict '20F0_10': 'Network Profile 1 - SIM PIN') | high
20F1_1 | Network Profile 2 - BO Version | decompiled.js@37671143 (dict '20F1_01': 'Network Profile 2 - BO Version') | high
20F1_3 | Network Profile 2 - BO URL | decompiled.js@37671188 (dict '20F1_03': 'Network Profile 2 - BO URL') | high
20F1_4 | Network Profile 2 - Message Timeout (s) | decompiled.js@37671229 (dict '20F1_04': 'Network Profile 2 - Message Timeout (s)') | high
20F1_5 | Network Profile 2 - Security Profile | decompiled.js@37671283 (dict '20F1_05': 'Network Profile 2 - Security Profile') | high
20F1_6 | Network Profile 2 - BO Profile | decompiled.js@37671334 (dict '20F1_06': 'Network Profile 2 - BO Profile') | high
20F1_7 | Network Profile 2 - APN Username (deprecated) | decompiled.js@37671379 (dict '20F1_07': 'Network Profile 2 - APN Username (deprecated)') | high
20F1_8 | Network Profile 2 - APN Username | decompiled.js@37671439 (dict '20F1_08': 'Network Profile 2 - APN Username') | high
20F1_9 | Network Profile 2 - APN Password | decompiled.js@37671486 (dict '20F1_09': 'Network Profile 2 - APN Password') | high
20F1_A | Network Profile 2 - SIM PIN (deprecated) | decompiled.js@37671533 (dict '20F1_0A': 'Network Profile 2 - SIM PIN (deprecated)') | high
20F1_B | Network Profile 2 - Preferred Network | decompiled.js@37671588 (dict '20F1_0B': 'Network Profile 2 - Preferred Network') | high
20F1_C | Netwrk Profile 2 - Use Preferred Only | decompiled.js@37671640 (dict '20F1_0C': 'Netwrk Profile 2 - Use Preferred Only') | high
20F1_D | Network Profile 2 - APN Authentication | decompiled.js@37671692 (dict '20F1_0D': 'Network Profile 2 - APN Authentication') | high
20F1_E | Network Profile 2 - Priority | decompiled.js@37671745 (dict '20F1_0E': 'Network Profile 2 - Priority') | high
20F1_F | Network Profile 2 - APN Name | decompiled.js@37671788 (dict '20F1_0F': 'Network Profile 2 - APN Name') | high
20F1_10 | Network Profile 2 - SIM PIN | decompiled.js@37671831 (dict '20F1_10': 'Network Profile 2 - SIM PIN') | high
20F2_1 | Network Profile 3 - BO Version | decompiled.js@37671873 (dict '20F2_01': 'Network Profile 3 - BO Version') | high
20F2_3 | Network Profile 3 - BO URL | decompiled.js@37671918 (dict '20F2_03': 'Network Profile 3 - BO URL') | high
20F2_4 | Network Profile 3 - Message Timeout (s) | decompiled.js@37671959 (dict '20F2_04': 'Network Profile 3 - Message Timeout (s)') | high
20F2_5 | Network Profile 3 - Security Profile | decompiled.js@37672013 (dict '20F2_05': 'Network Profile 3 - Security Profile') | high
20F2_6 | Network Profile 3 - BO Profile | decompiled.js@37672064 (dict '20F2_06': 'Network Profile 3 - BO Profile') | high
20F2_7 | Network Profile 3 - APN Username (deprecated) | decompiled.js@37672109 (dict '20F2_07': 'Network Profile 3 - APN Username (deprecated)') | high
20F2_8 | Network Profile 3 - APN Username | decompiled.js@37672169 (dict '20F2_08': 'Network Profile 3 - APN Username') | high
20F2_9 | Network Profile 3 - APN Password | decompiled.js@37672216 (dict '20F2_09': 'Network Profile 3 - APN Password') | high
20F2_A | Network Profile 3 - SIM PIN (deprecated) | decompiled.js@37672263 (dict '20F2_0A': 'Network Profile 3 - SIM PIN (deprecated)') | high
20F2_B | Network Profile 3 - Preferred Network | decompiled.js@37672318 (dict '20F2_0B': 'Network Profile 3 - Preferred Network') | high
20F2_C | Network Profile 3 - Use Preferred Only | decompiled.js@37672370 (dict '20F2_0C': 'Network Profile 3 - Use Preferred Only') | high
20F2_D | Network Profile 3 - APN Authentication | decompiled.js@37672423 (dict '20F2_0D': 'Network Profile 3 - APN Authentication') | high
20F2_E | Network Profile 3 - Priority | decompiled.js@37672476 (dict '20F2_0E': 'Network Profile 3 - Priority') | high
20F2_F | Network Profile 3 - APN Name | decompiled.js@37672519 (dict '20F2_0F': 'Network Profile 3 - APN Name') | high
20F2_10 | Network Profile 3 - SIM PIN | decompiled.js@37672562 (dict '20F2_10': 'Network Profile 3 - SIM PIN') | high
20F3_1 | Network Profile 4 - BO Version | decompiled.js@37672604 (dict '20F3_01': 'Network Profile 4 - BO Version') | high
20F3_3 | Network Profile 4 - BO URL | decompiled.js@37672649 (dict '20F3_03': 'Network Profile 4 - BO URL') | high
20F3_4 | Network Profile 4 - Message Timeout (s) | decompiled.js@37672690 (dict '20F3_04': 'Network Profile 4 - Message Timeout (s)') | high
20F3_5 | Network Profile 4 - Security Profile | decompiled.js@37672744 (dict '20F3_05': 'Network Profile 4 - Security Profile') | high
20F3_6 | Network Profile 4 - BO Profile | decompiled.js@37672795 (dict '20F3_06': 'Network Profile 4 - BO Profile') | high
20F3_7 | Network Profile 4 - APN Username (deprecated) | decompiled.js@37672840 (dict '20F3_07': 'Network Profile 4 - APN Username (deprecated)') | high
20F3_8 | Network Profile 4 - APN Username | decompiled.js@37672900 (dict '20F3_08': 'Network Profile 4 - APN Username') | high
20F3_9 | Network Profile 4 - APN Password | decompiled.js@37672947 (dict '20F3_09': 'Network Profile 4 - APN Password') | high
20F3_A | Network Profile 4 - SIM PIN (deprecated) | decompiled.js@37672994 (dict '20F3_0A': 'Network Profile 4 - SIM PIN (deprecated)') | high
20F3_B | Network Profile 4 - Preferred Network | decompiled.js@37673049 (dict '20F3_0B': 'Network Profile 4 - Preferred Network') | high
20F3_C | Network Profile 4 - Use Preferred Only | decompiled.js@37673101 (dict '20F3_0C': 'Network Profile 4 - Use Preferred Only') | high
20F3_D | Network Profile 4 - APN Authentication | decompiled.js@37673154 (dict '20F3_0D': 'Network Profile 4 - APN Authentication') | high
20F3_E | Network Profile 4 - Priority | decompiled.js@37673207 (dict '20F3_0E': 'Network Profile 4 - Priority') | high
20F3_F | Network Profile 4 - APN Name | decompiled.js@37673250 (dict '20F3_0F': 'Network Profile 4 - APN Name') | high
20F3_10 | Network Profile 4 - SIM PIN | decompiled.js@37673293 (dict '20F3_10': 'Network Profile 4 - SIM PIN') | high
20F4_0 | Network Profile Connection Attempts | decompiled.js@37673335 (dict '20F4_00': 'Network Profile Connection Attempts') | high
2100_0 | Mobile - APN name | decompiled.js@37673385 (dict '2100_00': 'Mobile - APN name') | high
2101_0 | Mobile - APN user | decompiled.js@37673417 (dict '2101_00': 'Mobile - APN user') | high
2102_0 | Mobile - APN password | decompiled.js@37673449 (dict '2102_00': 'Mobile - APN password') | high
2103_0 | Mobile - SIM PIN | decompiled.js@37673485 (dict '2103_00': 'Mobile - SIM PIN') | high
2104_0 | Mobile - SIM IMSI | decompiled.js@37673516 (dict '2104_00': 'Mobile - SIM IMSI') | high
2105_0 | Mobile - SIM ICCID | decompiled.js@37673548 (dict '2105_00': 'Mobile - SIM ICCID') | high
2106_0 | Mobile - Connection Delay | decompiled.js@37673581 (dict '2106_00': 'Mobile - Connection Delay') | high
2107_0 | Mobile - Connection Attempts | decompiled.js@37673621 (dict '2107_00': 'Mobile - Connection Attempts') | high
2108_0 | Mobile - Retry Behaviour | decompiled.js@37673664 (dict '2108_00': 'Mobile - Retry Behaviour') | high
2109_0 | Mobile - Band | decompiled.js@37673703 (dict '2109_00': 'Mobile - Band') | high
2110_0 | Mobile - Signal Strength | decompiled.js@37673731 (dict '2110_00': 'Mobile - Signal Strength') | high
2111_0 | Mobile - Weak Signal Threshold | decompiled.js@37673770 (dict '2111_00': 'Mobile - Weak Signal Threshold') | high
2112_0 | Mobile - Network Operator | decompiled.js@37673815 (dict '2112_00': 'Mobile - Network Operator') | high
2113_0 | Mobile - Network Mode | decompiled.js@37673855 (dict '2113_00': 'Mobile - Network Mode') | high
2114_0 | Mobile - Network Technology | decompiled.js@37673891 (dict '2114_00': 'Mobile - Network Technology') | high
2115_0 | Proxy address and port | decompiled.js@37673933 (dict '2115_00': 'Proxy address and port') | high
2116_0 | Proxy username | decompiled.js@37673970 (dict '2116_00': 'Proxy username') | high
2117_0 | Proxy enabled | decompiled.js@37673999 (dict '2117_00': 'Proxy enabled') | high
2118_0 | Modem Manufacturer | decompiled.js@37674027 (dict '2118_00': 'Modem Manufacturer') | high
2119_0 | Moden Model | decompiled.js@37674060 (dict '2119_00': 'Moden Model') | high
2120_0 | Modem Revision | decompiled.js@37674086 (dict '2120_00': 'Modem Revision') | high
2121_0 | Modem IMEI | decompiled.js@37674115 (dict '2121_00': 'Modem IMEI') | high
2124_0 | Informational Status Notifications | decompiled.js@37674140 (dict '2124_00': 'Informational Status Notifications') | high
2125_0 | Socket 1 - Socket type | decompiled.js@37674189 (dict '2125_00': 'Socket 1 - Socket type') | high
2126_0 | Authorization mode | decompiled.js@37674226 (dict '2126_00': 'Authorization mode') | high
2127_0 | Offline action - NFC | decompiled.js@37674259 (dict '2127_00': 'Offline action - NFC') | high
2128_0 | Socket 1 - Start Max. Current (A) | decompiled.js@37674294 (dict '2128_00': 'Socket 1 - Start Max. Current (A)') | high
2129_0 | Socket 1 - Max current (A) | decompiled.js@37674342 (dict '2129_00': 'Socket 1 - Max current (A)') | high
212A_0 | Socket 1 - External Max. Current (A) | decompiled.js@37674383 (dict '212A_00': 'Socket 1 - External Max. Current (A)') | high
212B_0 | Socket 1 - Standard LB Max Current (A) | decompiled.js@37674434 (dict '212B_00': 'Socket 1 - Standard LB Max Current (A)') | high
212C_0 | Socket 1 - Active Max Current (A) | decompiled.js@37674487 (dict '212C_00': 'Socket 1 - Active Max Current (A)') | high
212D_0 | Socket 1 - Active LB Min Current (A) | decompiled.js@37674535 (dict '212D_00': 'Socket 1 - Active LB Min Current (A)') | high
212E_1 | P1 Status - Read Status | decompiled.js@37674586 (dict '212E_01': 'P1 Status - Read Status') | high
212E_2 | P1 Status - Version | decompiled.js@37674624 (dict '212E_02': 'P1 Status - Version') | high
212E_3 | P1 Status - Timestamp | decompiled.js@37674658 (dict '212E_03': 'P1 Status - Timestamp') | high
212F_1 | Main Measurements 1 | decompiled.js@37674694 (dict '212F_01': 'Main Measurements 1') | high
212F_2 | Main Measurements 2 | decompiled.js@37674728 (dict '212F_02': 'Main Measurements 2') | high
212F_3 | Main Measurements 3 | decompiled.js@37674762 (dict '212F_03': 'Main Measurements 3') | high
2130_0 | Simplified Max Current (A) | decompiled.js@37674796 (dict '2130_00': 'Simplified Max Current (A)') | high
2131_0 | Start Up Delay (s) | decompiled.js@37674837 (dict '2131_00': 'Start Up Delay (s)') | high
2132_0 | Swich Error Delay (s) | decompiled.js@37674870 (dict '2132_00': 'Swich Error Delay (s)') | high
2133_0 | Current Error Delay (s) | decompiled.js@37674906 (dict '2133_00': 'Current Error Delay (s)') | high
2134_0 | HighFrequency Error Delay (s) | decompiled.js@37674944 (dict '2134_00': 'HighFrequency Error Delay (s)') | high
2135_0 | EV Connection timeout (s) | decompiled.js@37674988 (dict '2135_00': 'EV Connection timeout (s)') | high
2136_0 | EV Disconnect timeout (s) | decompiled.js@37675028 (dict '2136_00': 'EV Disconnect timeout (s)') | high
2137_0 | EV Disconnect action | decompiled.js@37675068 (dict '2137_00': 'EV Disconnect action') | high
2138_0 | NFC Reader Type | decompiled.js@37675103 (dict '2138_00': 'NFC Reader Type') | high
2139_0 | NFC Scan Interval (s) | decompiled.js@37675133 (dict '2139_00': 'NFC Scan Interval (s)') | high
213A_0 | NFC Reader Model | decompiled.js@37675169 (dict '213A_00': 'NFC Reader Model') | high
213B_0 | White list enabled | decompiled.js@37675200 (dict '213B_00': 'White list enabled') | high
213C_0 | Online NFC action | decompiled.js@37675233 (dict '213C_00': 'Online NFC action') | high
213D_0 | Local list enabled | decompiled.js@37675265 (dict '213D_00': 'Local list enabled') | high
213E_0 | Offline action - Local list | decompiled.js@37675298 (dict '213E_00': 'Offline action - Local list') | high
2140_0 | NFC Reader Tag Delay (s) | decompiled.js@37675340 (dict '2140_00': 'NFC Reader Tag Delay (s)') | high
2153_0 | Max time to Open S2 | decompiled.js@37675379 (dict '2153_00': 'Max time to Open S2') | high
2159_0 | ZE ready | decompiled.js@37675413 (dict '2159_00': 'ZE ready') | high
215D_0 | Disable 105 percent overcurrent | decompiled.js@37675436 (dict '215D_00': 'Disable 105 percent overcurrent') | high
215E_0 | Restart after Power Outage | decompiled.js@37675482 (dict '215E_00': 'Restart after Power Outage') | high
215F_0 | External Max. Current (A) | decompiled.js@37675523 (dict '215F_00': 'External Max. Current (A)') | high
2160_0 | External Min. Current (A) | decompiled.js@37675563 (dict '2160_00': 'External Min. Current (A)') | high
2161_0 | Active Max. Current (A) | decompiled.js@37675603 (dict '2161_00': 'Active Max. Current (A)') | high
2165_1 | DSC 0 - Status | decompiled.js@37675641 (dict '2165_01': 'DSC 0 - Status') | high
2165_2 | DSC 0 - Safe current (A) | decompiled.js@37675670 (dict '2165_02': 'DSC 0 - Safe current (A)') | high
2165_3 | DSC 0 - Max. current (A) | decompiled.js@37675709 (dict '2165_03': 'DSC 0 - Max. current (A)') | high
2165_4 | DSC 0 - Valid to | decompiled.js@37675748 (dict '2165_04': 'DSC 0 - Valid to') | high
2166_1 | DSC 1 - Status | decompiled.js@37675779 (dict '2166_01': 'DSC 1 - Status') | high
2166_2 | DSC 1 - Safe current (A) | decompiled.js@37675808 (dict '2166_02': 'DSC 1 - Safe current (A)') | high
2166_3 | DSC 1 - Max. current (A) | decompiled.js@37675847 (dict '2166_03': 'DSC 1 - Max. current (A)') | high
2166_4 | DSC 1 - Valid to | decompiled.js@37675886 (dict '2166_04': 'DSC 1 - Valid to') | high
2167_1 | DSC 2 - Status | decompiled.js@37675917 (dict '2167_01': 'DSC 2 - Status') | high
2167_2 | DSC 2 - Safe current (A) | decompiled.js@37675946 (dict '2167_02': 'DSC 2 - Safe current (A)') | high
2167_3 | DSC 2 - Max. current (A) | decompiled.js@37675985 (dict '2167_03': 'DSC 2 - Max. current (A)') | high
2167_4 | DSC 2 - Valid to | decompiled.js@37676024 (dict '2167_04': 'DSC 2 - Valid to') | high
2168_0 | Time to unlock not charging (s) | decompiled.js@37676102 (dict '2168_00': 'Time to unlock not charging (s)') | high
2169_0 | Max. Allowed Outage Duration (s) | decompiled.js@37676055 (dict '2169_00': 'Max. Allowed Outage Duration (s)') | high
216A_0 | Eichrecht enabled | decompiled.js@37676148 (dict '216A_00': 'Eichrecht enabled') | high
216B_0 | Signed meter values at Interval | decompiled.js@37676180 (dict '216B_00': 'Signed meter values at Interval') | high
216C_0 | Direct external suspend signal | decompiled.js@37676226 (dict '216C_00': 'Direct external suspend signal') | high
216D_0 | QR code display time (s) | decompiled.js@37676271 (dict '216D_00': 'QR code display time (s)') | high
216F_0 | Signed meter values at Start & Stop | decompiled.js@37676310 (dict '216F_00': 'Signed meter values at Start & Stop') | high
2171_0 | Heart beat mode enabled | decompiled.js@37676360 (dict '2171_00': 'Heart beat mode enabled') | high
2172_0 | Heart beat intensity | decompiled.js@37676398 (dict '2172_00': 'Heart beat intensity') | high
2173_0 | Socket 1.2 Max current (A) | decompiled.js@37676433 (dict '2173_00': 'Socket 1.2 Max current (A)') | high
2174_0 | Maximum imbalance current (A) | decompiled.js@37676474 (dict '2174_00': 'Maximum imbalance current (A)') | high
2175_0 | External Modbus Support | decompiled.js@37676518 (dict '2175_00': 'External Modbus Support') | high
2176_0 | Device ID | decompiled.js@37676556 (dict '2176_00': 'Device ID') | high
2177_0 | QR URL Socket #1 | decompiled.js@37676580 (dict '2177_00': 'QR URL Socket #1') | high
2178_0 | QR URL Socket #2 | decompiled.js@37676611 (dict '2178_00': 'QR URL Socket #2') | high
2179_0 | Dynamic QR code enabled | decompiled.js@37676642 (dict '2179_00': 'Dynamic QR code enabled') | high
2180_1 | SCN - Network name | decompiled.js@37676680 (dict '2180_01': 'SCN - Network name') | high
2180_2 | SCN - Socket ID | decompiled.js@37676713 (dict '2180_02': 'SCN - Socket ID') | high
2180_3 | SCN - Amount of sockets | decompiled.js@37676743 (dict '2180_03': 'SCN - Amount of sockets') | high
2180_4 | SCN - Alternating period (s) | decompiled.js@37676781 (dict '2180_04': 'SCN - Alternating period (s)') | high
2180_5 | SCN - Total current (A) | decompiled.js@37676824 (dict '2180_05': 'SCN - Total current (A)') | high
2180_6 | SCN - Socket safe current (A) | decompiled.js@37676862 (dict '2180_06': 'SCN - Socket safe current (A)') | high
2180_7 | SCN - Phase mapping 1 | decompiled.js@37676906 (dict '2180_07': 'SCN - Phase mapping 1') | high
2180_8 | SCN - Is unlocked | decompiled.js@37676942 (dict '2180_08': 'SCN - Is unlocked') | high
2180_9 | SCN - Phase mapping 2 | decompiled.js@37676974 (dict '2180_09': 'SCN - Phase mapping 2') | high
2180_A | SCN - Total safe current (A) | decompiled.js@37677010 (dict '2180_0A': 'SCN - Total safe current (A)') | high
2182_0 | Random my clock aligned msg (s) | decompiled.js@37677053 (dict '2182_00': 'Random my clock aligned msg (s)') | high
2183_0 | Cover lock enabled | decompiled.js@37677099 (dict '2183_00': 'Cover lock enabled') | high
2184_0 | Time to report not charging (s) | decompiled.js@37677132 (dict '2184_00': 'Time to report not charging (s)') | high
2185_0 | Allow 1- and 3-phased charing | decompiled.js@37677178 (dict '2185_00': 'Allow 1- and 3-phased charing') | high
2187_0 | Last time Configuration Changed | decompiled.js@37677222 (dict '2187_00': 'Last time Configuration Changed') | high
2188_0 | Giro-e ready | decompiled.js@37677268 (dict '2188_00': 'Giro-e ready') | high
2189_0 | Max. Allowed Phases | decompiled.js@37677295 (dict '2189_00': 'Max. Allowed Phases') | high
218A_0 | Tx Start Point | decompiled.js@37677329 (dict '218A_00': 'Tx Start Point') | high
218B_0 | Tx Stop Point | decompiled.js@37677358 (dict '218B_00': 'Tx Stop Point') | high
218E_0 | Max energy on invalid id | decompiled.js@37677386 (dict '218E_00': 'Max energy on invalid id') | high
218F_1 | Limiting Factors 1 | decompiled.js@37677425 (dict '218F_01': 'Limiting Factors 1') | high
218F_2 | Limiting Factors 2 | decompiled.js@37677458 (dict '218F_02': 'Limiting Factors 2') | high
2190_0 | NFC Led Enabled | decompiled.js@37677491 (dict '2190_00': 'NFC Led Enabled') | high
2191_1 | P1 Interface - Interface | decompiled.js@37677521 (dict '2191_01': 'P1 Interface - Interface') | high
2191_2 | P1 Interface - Server Address | decompiled.js@37677560 (dict '2191_02': 'P1 Interface - Server Address') | high
2191_3 | P1 Interface - Server Port | decompiled.js@37677604 (dict '2191_03': 'P1 Interface - Server Port') | high
2192_0 | Payment Options | decompiled.js@37677645 (dict '2192_00': 'Payment Options') | high
21A0_0 | License Key - Unique ID | decompiled.js@37677675 (dict '21A0_00': 'License Key - Unique ID') | high
21A1_0 | License Key - Feature Code | decompiled.js@37677713 (dict '21A1_00': 'License Key - Feature Code') | high
21A2_0 | License Key Unlocked features | decompiled.js@37677754 (dict '21A2_00': 'License Key Unlocked features') | high
21A3_0 | ERP Password | decompiled.js@37677798 (dict '21A3_00': 'ERP Password') | high
21B0_0 | Strict PE Measurement | decompiled.js@37677825 (dict '21B0_00': 'Strict PE Measurement') | high
21B1_0 | RDP Level | decompiled.js@37677861 (dict '21B1_00': 'RDP Level') | high
21B2_0 | SSA Enabled | decompiled.js@37677885 (dict '21B2_00': 'SSA Enabled') | high
21B3_0 | Temperary Access Expired | decompiled.js@37677911 (dict '21B3_00': 'Temperary Access Expired') | high
21B4_0 | Admin Password is default | decompiled.js@37677950 (dict '21B4_00': 'Admin Password is default') | high
21B5_0 | Modem Enabled | decompiled.js@37677990 (dict '21B5_00': 'Modem Enabled') | high
21B6_0 | CS Operational Time | decompiled.js@37678018 (dict '21B6_00': 'CS Operational Time') | high
21B7_0 | Secure EEProm | decompiled.js@37678052 (dict '21B7_00': 'Secure EEProm') | high
21B8_0 | Auxiliary Board Information | decompiled.js@37678080 (dict '21B8_00': 'Auxiliary Board Information') | high
21B9_0 | Charging Profile Max. Random Delay | decompiled.js@37678122 (dict '21B9_00': 'Charging Profile Max. Random Delay') | high
21BA_0 | Auxiliary Board Revision | decompiled.js@37678171 (dict '21BA_00': 'Auxiliary Board Revision') | high
2200_0 | Temperature Mode | decompiled.js@37678210 (dict '2200_00': 'Temperature Mode') | high
2201_0 | Temperature (Â°C) | decompiled.js@37678241 (dict '2201_00': 'Temperature (Â°C)') | high
2202_0 | Alarm value low (Â°C) | decompiled.js@37678272 (dict '2202_00': 'Alarm value low (Â°C)') | high
2203_0 | Alarm value high (Â°C) | decompiled.js@37678307 (dict '2203_00': 'Alarm value high (Â°C)') | high
2204_0 | Check interval (s) | decompiled.js@37678343 (dict '2204_00': 'Check interval (s)') | high
2205_0 | Log interval (s) | decompiled.js@37678376 (dict '2205_00': 'Log interval (s)') | high
2206_0 | Mode | decompiled.js@37678407 (dict '2206_00': 'Mode') | high
2207_0 | Tilt Sensor - Value X | decompiled.js@37678426 (dict '2207_00': 'Tilt Sensor - Value X') | high
2208_0 | Tilt Sensor - Value Y | decompiled.js@37678462 (dict '2208_00': 'Tilt Sensor - Value Y') | high
2209_0 | Tilt Sensor - Value Z | decompiled.js@37678498 (dict '2209_00': 'Tilt Sensor - Value Z') | high
2210_0 | Tilt Sensor - Setpoint X | decompiled.js@37678534 (dict '2210_00': 'Tilt Sensor - Setpoint X') | high
2211_0 | Tilt Sensor - Setpoint Y | decompiled.js@37678573 (dict '2211_00': 'Tilt Sensor - Setpoint Y') | high
2212_0 | Tilt Sensor - Setpoint Z | decompiled.js@37678612 (dict '2212_00': 'Tilt Sensor - Setpoint Z') | high
2213_0 | Tilt Sensor - Margin X | decompiled.js@37678651 (dict '2213_00': 'Tilt Sensor - Margin X') | high
2214_0 | Tilt Sensor - Margin Y | decompiled.js@37678688 (dict '2214_00': 'Tilt Sensor - Margin Y') | high
2215_0 | Tilt Sensor - Margin Z | decompiled.js@37678725 (dict '2215_00': 'Tilt Sensor - Margin Z') | high
2216_0 | Tilt Sensor - Log interval (s) | decompiled.js@37678762 (dict '2216_00': 'Tilt Sensor - Log interval (s)') | high
2218_0 | Socket 1 - Meter Type | decompiled.js@37678807 (dict '2218_00': 'Socket 1 - Meter Type') | high
2219_0 | Socket 1 - Pulses per kWh | decompiled.js@37678843 (dict '2219_00': 'Socket 1 - Pulses per kWh') | high
2221_3 | Socket 1 - Voltage L1N (V) | decompiled.js@37678883 (dict '2221_03': 'Socket 1 - Voltage L1N (V)') | high
2221_4 | Socket 1 - Voltage L2N (V) | decompiled.js@37678924 (dict '2221_04': 'Socket 1 - Voltage L2N (V)') | high
2221_5 | Socket 1 - Voltage L3N (V) | decompiled.js@37678965 (dict '2221_05': 'Socket 1 - Voltage L3N (V)') | high
2221_6 | Socket 1 - Voltage L1L2 (V) | decompiled.js@37679006 (dict '2221_06': 'Socket 1 - Voltage L1L2 (V)') | high
2221_7 | Socket 1 - Voltage L2L3 (V) | decompiled.js@37679048 (dict '2221_07': 'Socket 1 - Voltage L2L3 (V)') | high
2221_8 | Socket 1 - Voltage L3L1 (V) | decompiled.js@37679090 (dict '2221_08': 'Socket 1 - Voltage L3L1 (V)') | high
2221_9 | Socket 1 - Current N (A) | decompiled.js@37679132 (dict '2221_09': 'Socket 1 - Current N (A)') | high
2221_A | Socket 1 - Current L1 (A) | decompiled.js@37679171 (dict '2221_0A': 'Socket 1 - Current L1 (A)') | high
2221_B | Socket 1 - Current L2 (A) | decompiled.js@37679211 (dict '2221_0B': 'Socket 1 - Current L2 (A)') | high
2221_C | Socket 1 - Current L3 (A) | decompiled.js@37679251 (dict '2221_0C': 'Socket 1 - Current L3 (A)') | high
2221_D | Socket 1 - Current Sum (A) | decompiled.js@37679291 (dict '2221_0D': 'Socket 1 - Current Sum (A)') | high
2221_E | Socket 1 - Cos L1 | decompiled.js@37679332 (dict '2221_0E': 'Socket 1 - Cos L1') | high
2221_F | Socket 1 - Cos L2 | decompiled.js@37679364 (dict '2221_0F': 'Socket 1 - Cos L2') | high
2221_10 | Socket 1 - Cos L3 | decompiled.js@37679396 (dict '2221_10': 'Socket 1 - Cos L3') | high
2221_11 | Socket 1 - Cos Sum | decompiled.js@37679428 (dict '2221_11': 'Socket 1 - Cos Sum') | high
2221_12 | Socket 1 - Frequency (Hz) | decompiled.js@37679461 (dict '2221_12': 'Socket 1 - Frequency (Hz)') | high
2221_13 | Socket 1 - Power Real L1 (kW) | decompiled.js@37679501 (dict '2221_13': 'Socket 1 - Power Real L1 (kW)') | high
2221_14 | Socket 1 - Power Real L2 (kW) | decompiled.js@37679545 (dict '2221_14': 'Socket 1 - Power Real L2 (kW)') | high
2221_15 | Socket 1 - Power Real L3 (kW) | decompiled.js@37679589 (dict '2221_15': 'Socket 1 - Power Real L3 (kW)') | high
2221_16 | Socket 1 - Power Real Sum (kW) | decompiled.js@37679633 (dict '2221_16': 'Socket 1 - Power Real Sum (kW)') | high
2221_17 | Socket 1 - Power Apperant L1 (kW) | decompiled.js@37679678 (dict '2221_17': 'Socket 1 - Power Apperant L1 (kW)') | high
2221_18 | Socket 1 - Power Apperant L2 (kW) | decompiled.js@37679726 (dict '2221_18': 'Socket 1 - Power Apperant L2 (kW)') | high
2221_19 | Socket 1 - Power Apperant L3 (kW) | decompiled.js@37679774 (dict '2221_19': 'Socket 1 - Power Apperant L3 (kW)') | high
2221_1A | Socket 1 - Power Apperant Sum (kW) | decompiled.js@37679822 (dict '2221_1A': 'Socket 1 - Power Apperant Sum (kW)') | high
2221_1B | Socket 1 - Power Reactive L1 (kW) | decompiled.js@37679871 (dict '2221_1B': 'Socket 1 - Power Reactive L1 (kW)') | high
2221_1C | Socket 1 - Power Reactive L2 (kW) | decompiled.js@37679919 (dict '2221_1C': 'Socket 1 - Power Reactive L2 (kW)') | high
2221_1D | Socket 1 - Power Reactive L3 (kW) | decompiled.js@37679967 (dict '2221_1D': 'Socket 1 - Power Reactive L3 (kW)') | high
2221_1E | Socket 1 - Power Reactive Sum (kW) | decompiled.js@37680015 (dict '2221_1E': 'Socket 1 - Power Reactive Sum (kW)') | high
2221_1F | Socket 1 - Energy Delivered L1 (kWh) | decompiled.js@37680064 (dict '2221_1F': 'Socket 1 - Energy Delivered L1 (kWh)') | high
2221_20 | Socket 1 - Energy Delivered L2 (kWh) | decompiled.js@37680115 (dict '2221_20': 'Socket 1 - Energy Delivered L2 (kWh)') | high
2221_21 | Socket 1 - Energy Delivered L3 (kWh) | decompiled.js@37680166 (dict '2221_21': 'Socket 1 - Energy Delivered L3 (kWh)') | high
2221_22 | Socket 1 - Energy Delivered Sum (kWh) | decompiled.js@37680217 (dict '2221_22': 'Socket 1 - Energy Delivered Sum (kWh)') | high
2221_23 | Socket 1 - Energy Consumed L1 (kWh) | decompiled.js@37680269 (dict '2221_23': 'Socket 1 - Energy Consumed L1 (kWh)') | high
2221_24 | Socket 1 - Energy Consumed L2 (kWh) | decompiled.js@37680319 (dict '2221_24': 'Socket 1 - Energy Consumed L2 (kWh)') | high
2221_25 | Socket 1 - Energy Consumed L3 (kWh) | decompiled.js@37680369 (dict '2221_25': 'Socket 1 - Energy Consumed L3 (kWh)') | high
2221_26 | Socket 1 - Energy Consumed Sum (kWh) | decompiled.js@37680419 (dict '2221_26': 'Socket 1 - Energy Consumed Sum (kWh)') | high
2221_27 | Socket 1 - Energy Apparent L1 | decompiled.js@37680470 (dict '2221_27': 'Socket 1 - Energy Apparent L1') | high
2221_28 | Socket 1 - Energy Apparent L2 | decompiled.js@37680514 (dict '2221_28': 'Socket 1 - Energy Apparent L2') | high
2221_29 | Socket 1 - Energy Apparent L3 | decompiled.js@37680558 (dict '2221_29': 'Socket 1 - Energy Apparent L3') | high
2221_2A | Socket 1 - Energy Apparent Sum | decompiled.js@37680602 (dict '2221_2A': 'Socket 1 - Energy Apparent Sum') | high
2221_2B | Socket 1 - Energy Reactive L1 | decompiled.js@37680647 (dict '2221_2B': 'Socket 1 - Energy Reactive L1') | high
2221_2C | Socket 1 - Energy Reactive L2 | decompiled.js@37680691 (dict '2221_2C': 'Socket 1 - Energy Reactive L2') | high
2221_2D | Socket 1 - Energy Reactive L3 | decompiled.js@37680735 (dict '2221_2D': 'Socket 1 - Energy Reactive L3') | high
2221_2E | Socket 1 - Energy Reactive Sum | decompiled.js@37680779 (dict '2221_2E': 'Socket 1 - Energy Reactive Sum') | high
2224_0 | Socket 1 - ADC Voltage CP High | decompiled.js@37680824 (dict '2224_00': 'Socket 1 - ADC Voltage CP High') | high
2225_0 | Socket 1 - ADC Voltage CP Low | decompiled.js@37680869 (dict '2225_00': 'Socket 1 - ADC Voltage CP Low') | high
2228_0 | Socket 2 - ADC Voltage CP High | decompiled.js@37680913 (dict '2228_00': 'Socket 2 - ADC Voltage CP High') | high
2229_0 | Socket 2 - ADC Voltage CP Low | decompiled.js@37680958 (dict '2229_00': 'Socket 2 - ADC Voltage CP Low') | high
2231_0 | Socket 1 - ADC Resistance PP | decompiled.js@37681002 (dict '2231_00': 'Socket 1 - ADC Resistance PP') | high
2233_0 | Socket 2 - ADC Resistance PP | decompiled.js@37681045 (dict '2233_00': 'Socket 2 - ADC Resistance PP') | high
2249_0 | Temperature sensor max. value (Â°C) | decompiled.js@37681088 (dict '2249_00': 'Temperature sensor max. value (Â°C)') | high
2249_1 | Temperature sensor min. value (Â°C) | decompiled.js@37681137 (dict '2249_01': 'Temperature sensor min. value (Â°C)') | high
2250_0 | Tamper detection | decompiled.js@37681186 (dict '2250_00': 'Tamper detection') | high
2300_0 | Led state - Unknown | decompiled.js@37681217 (dict '2300_00': 'Led state - Unknown') | high
2301_0 | Led state - Off | decompiled.js@37681251 (dict '2301_00': 'Led state - Off') | high
2302_0 | Led state - Booting | decompiled.js@37681281 (dict '2302_00': 'Led state - Booting') | high
2303_0 | Led state - Booting Check mains | decompiled.js@37681315 (dict '2303_00': 'Led state - Booting Check mains') | high
2304_0 | Led state - Available | decompiled.js@37681361 (dict '2304_00': 'Led state - Available') | high
2305_0 | Led state - Authorising | decompiled.js@37681397 (dict '2305_00': 'Led state - Authorising') | high
2306_0 | Led state - Authorized | decompiled.js@37681435 (dict '2306_00': 'Led state - Authorized') | high
2307_0 | Led state - Cable Connected | decompiled.js@37681472 (dict '2307_00': 'Led state - Cable Connected') | high
2308_0 | Led state - EV Connected | decompiled.js@37681514 (dict '2308_00': 'Led state - EV Connected') | high
2309_0 | Led state - Preparing | decompiled.js@37681553 (dict '2309_00': 'Led state - Preparing') | high
2310_0 | Led state - Waiting on EV | decompiled.js@37681589 (dict '2310_00': 'Led state - Waiting on EV') | high
2311_0 | Led state - Charging Normal | decompiled.js@37681629 (dict '2311_00': 'Led state - Charging Normal') | high
2312_0 | Led state - Charging Simplified | decompiled.js@37681671 (dict '2312_00': 'Led state - Charging Simplified') | high
2313_0 | Led state - Overcurrent | decompiled.js@37681717 (dict '2313_00': 'Led state - Overcurrent') | high
2314_0 | Led state - HF Switching | decompiled.js@37681755 (dict '2314_00': 'Led state - HF Switching') | high
2315_0 | Led state - EV Disconnecting | decompiled.js@37681794 (dict '2315_00': 'Led state - EV Disconnecting') | high
2316_0 | Led state - Wait on EV | decompiled.js@37681837 (dict '2316_00': 'Led state - Wait on EV') | high
2317_0 | Led state - Wait on Disconnect | decompiled.js@37681874 (dict '2317_00': 'Led state - Wait on Disconnect') | high
2318_0 | Led state - Protective Earth Fault | decompiled.js@37681919 (dict '2318_00': 'Led state - Protective Earth Fault') | high
2319_0 | Led state - Power Line Error | decompiled.js@37681968 (dict '2319_00': 'Led state - Power Line Error') | high
2320_0 | Led state - Contactor Fault | decompiled.js@37682011 (dict '2320_00': 'Led state - Contactor Fault') | high
2321_0 | Led state - Charging Error | decompiled.js@37682053 (dict '2321_00': 'Led state - Charging Error') | high
2322_0 | Led state - Power Failure | decompiled.js@37682094 (dict '2322_00': 'Led state - Power Failure') | high
2323_0 | Led state - Temperature Error | decompiled.js@37682134 (dict '2323_00': 'Led state - Temperature Error') | high
2324_0 | Led state - Illegal CP Value | decompiled.js@37682178 (dict '2324_00': 'Led state - Illegal CP Value') | high
2325_0 | Led state - Illegal PP Value | decompiled.js@37682221 (dict '2325_00': 'Led state - Illegal PP Value') | high
2326_0 | Led state - Too Many Restarts | decompiled.js@37682264 (dict '2326_00': 'Led state - Too Many Restarts') | high
2327_0 | Led state - Error | decompiled.js@37682308 (dict '2327_00': 'Led state - Error') | high
2328_0 | Led state - Error Message | decompiled.js@37682340 (dict '2328_00': 'Led state - Error Message') | high
2329_0 | Led state - Not Authorised Error | decompiled.js@37682380 (dict '2329_00': 'Led state - Not Authorised Error') | high
2330_0 | Led state - Cable Not Supported | decompiled.js@37682427 (dict '2330_00': 'Led state - Cable Not Supported') | high
2331_0 | Led state - S2 not Opened | decompiled.js@37682473 (dict '2331_00': 'Led state - S2 not Opened') | high
2332_0 | Led state - Message timeout | decompiled.js@37682513 (dict '2332_00': 'Led state - Message timeout') | high
2333_0 | Led state - Reserved | decompiled.js@37682555 (dict '2333_00': 'Led state - Reserved') | high
2334_0 | Led state - Inoperative | decompiled.js@37682590 (dict '2334_00': 'Led state - Inoperative') | high
2335_0 | Led state - Load Balancing Limited | decompiled.js@37682628 (dict '2335_00': 'Led state - Load Balancing Limited') | high
2336_0 | Led state - Load Balancing Forced Off | decompiled.js@37682677 (dict '2336_00': 'Led state - Load Balancing Forced Off') | high
2338_0 | Led state - Inactive | decompiled.js@37682729 (dict '2338_00': 'Led state - Inactive') | high
2350_0 | Led state - Heartbeat | decompiled.js@37682764 (dict '2350_00': 'Led state - Heartbeat') | high
2400_1 | Master Tag - Enabled | decompiled.js@37682800 (dict '2400_01': 'Master Tag - Enabled') | high
2400_2 | Master Tag - ID | decompiled.js@37682835 (dict '2400_02': 'Master Tag - ID') | high
2401_0 | Emergency Services ID | decompiled.js@37682865 (dict '2401_00': 'Emergency Services ID') | high
2501_1 | Socket 1 - Mainstate | decompiled.js@37682901 (dict '2501_01': 'Socket 1 - Mainstate') | high
2501_2 | Socket 1 - LED state | decompiled.js@37682936 (dict '2501_02': 'Socket 1 - LED state') | high
2501_3 | Socket 1 - Power state | decompiled.js@37682971 (dict '2501_03': 'Socket 1 - Power state') | high
2501_4 | Socket 1 - Mode3 state | decompiled.js@37683008 (dict '2501_04': 'Socket 1 - Mode3 state') | high
2502_1 | Socket 2 - Main state | decompiled.js@37683045 (dict '2502_01': 'Socket 2 - Main state') | high
2502_2 | Socket 2 - LED state | decompiled.js@37683081 (dict '2502_02': 'Socket 2 - LED state') | high
2502_3 | Socket 2 - Power state | decompiled.js@37683116 (dict '2502_03': 'Socket 2 - Power state') | high
2502_4 | Socket 2 - Mode3 state | decompiled.js@37683153 (dict '2502_04': 'Socket 2 - Mode3 state') | high
2511_0 | Socket 1 - CP voltage high (V) | decompiled.js@37683190 (dict '2511_00': 'Socket 1 - CP voltage high (V)') | high
2511_1 | Socket 1 - CP voltage low (V) | decompiled.js@37683235 (dict '2511_01': 'Socket 1 - CP voltage low (V)') | high
2511_2 | Socket 1 - PP resistance (Î©) | decompiled.js@37683279 (dict '2511_02': 'Socket 1 - PP resistance (Î©)') | high
2511_3 | Socket 1 - PWM duty cycle (%) | decompiled.js@37683322 (dict '2511_03': 'Socket 1 - PWM duty cycle (%)') | high
2512_0 | Socket 2 - CP voltage high (V) | decompiled.js@37683366 (dict '2512_00': 'Socket 2 - CP voltage high (V)') | high
2512_1 | Socket 2 - CP voltage low (V) | decompiled.js@37683411 (dict '2512_01': 'Socket 2 - CP voltage low (V)') | high
2512_2 | Socket 2 - PP resistance (Î©) | decompiled.js@37683455 (dict '2512_02': 'Socket 2 - PP resistance (Î©)') | high
2512_3 | Socket 2 - PWM duty cycle (%) | decompiled.js@37683498 (dict '2512_03': 'Socket 2 - PWM duty cycle (%)') | high
2522_1 | Central Modbus TCP/IP - Enabled | decompiled.js@37683542 (dict '2522_01': 'Central Modbus TCP/IP - Enabled') | high
2522_2 | Central Modbus TCP/IP - Client Type | decompiled.js@37683588 (dict '2522_02': 'Central Modbus TCP/IP - Client Type') | high
2522_4 | Central Modbus TCP/IP - IP Address | decompiled.js@37683638 (dict '2522_04': 'Central Modbus TCP/IP - IP Address') | high
2522_6 | Central Modbus TCP/IP - Client Address | decompiled.js@37683687 (dict '2522_06': 'Central Modbus TCP/IP - Client Address') | high
2523_1 | Smart Modbus TCP/IP - Enabled | decompiled.js@37683740 (dict '2523_01': 'Smart Modbus TCP/IP - Enabled') | high
2523_2 | Smart Modbus TCP/IP - Client Type | decompiled.js@37683784 (dict '2523_02': 'Smart Modbus TCP/IP - Client Type') | high
2523_4 | Smart Modbus TCP/IP - IP address | decompiled.js@37683832 (dict '2523_04': 'Smart Modbus TCP/IP - IP address') | high
2523_6 | Smart Modbus TCP/IP - Client address | decompiled.js@37683879 (dict '2523_06': 'Smart Modbus TCP/IP - Client address') | high
2530_1 | EMS Data source | decompiled.js@37683930 (dict '2530_01': 'EMS Data source') | high
2530_2 | EMS Socket Balancing | decompiled.js@37683960 (dict '2530_02': 'EMS Socket Balancing') | high
2530_3 | EMS SCN Balancing | decompiled.js@37683995 (dict '2530_03': 'EMS SCN Balancing') | high
2530_4 | ValidityTime (s) | decompiled.js@37684027 (dict '2530_04': 'ValidityTime (s)') | high
2540_0 | Modbus TCP/IP connection state | decompiled.js@37684058 (dict '2540_00': 'Modbus TCP/IP connection state') | high
2541_0 | Socket 1 public key | decompiled.js@37684103 (dict '2541_00': 'Socket 1 public key') | high
2542_0 | Socket 2 public key | decompiled.js@37684137 (dict '2542_00': 'Socket 2 public key') | high
2560_0 | Central Meter - Measurands | decompiled.js@37684171 (dict '2560_00': 'Central Meter - Measurands') | high
2561_0 | Central Meter - Register Numbers | decompiled.js@37684212 (dict '2561_00': 'Central Meter - Register Numbers') | high
2562_0 | Central Meter - Data Type | decompiled.js@37684259 (dict '2562_00': 'Central Meter - Data Type') | high
2563_0 | Central Meter - Scale Factor | decompiled.js@37684299 (dict '2563_00': 'Central Meter - Scale Factor') | high
2564_0 | Central Meter - Word Order | decompiled.js@37684342 (dict '2564_00': 'Central Meter - Word Order') | high
2564_1 | Central Meter - Update time | decompiled.js@37684383 (dict '2564_01': 'Central Meter - Update time') | high
2564_2 | Central Meter - Read Timeout | decompiled.js@37684425 (dict '2564_02': 'Central Meter - Read Timeout') | high
2564_3 | Central Meter - Function Code | decompiled.js@37684468 (dict '2564_03': 'Central Meter - Function Code') | high
2565_0 | Central Meter - Baudrate | decompiled.js@37684512 (dict '2565_00': 'Central Meter - Baudrate') | high
2565_1 | Central Meter - Parity | decompiled.js@37684551 (dict '2565_01': 'Central Meter - Parity') | high
2565_2 | Central Meter = Address | decompiled.js@37684588 (dict '2565_02': 'Central Meter = Address') | high
2570_0 | Smart Meter - Measurands | decompiled.js@37684626 (dict '2570_00': 'Smart Meter - Measurands') | high
2571_0 | Smart Meter - Register Numbers | decompiled.js@37684665 (dict '2571_00': 'Smart Meter - Register Numbers') | high
2572_0 | Smart Meter - Data Type | decompiled.js@37684710 (dict '2572_00': 'Smart Meter - Data Type') | high
2573_0 | Smart Meter - Scale Factor | decompiled.js@37684748 (dict '2573_00': 'Smart Meter - Scale Factor') | high
2574_0 | Smart Meter - Word Order | decompiled.js@37684789 (dict '2574_00': 'Smart Meter - Word Order') | high
2574_1 | Smart Meter - Update time | decompiled.js@37684828 (dict '2574_01': 'Smart Meter - Update time') | high
2574_2 | Smart Meter - Read Timeout | decompiled.js@37684868 (dict '2574_02': 'Smart Meter - Read Timeout') | high
2574_3 | Smart Meter - Function Code | decompiled.js@37684909 (dict '2574_03': 'Smart Meter - Function Code') | high
2575_0 | Smart Meter - Baudrate | decompiled.js@37684951 (dict '2575_00': 'Smart Meter - Baudrate') | high
2575_1 | Smart Meter - Parity | decompiled.js@37684988 (dict '2575_01': 'Smart Meter - Parity') | high
2575_2 | Smart Meter - Address | decompiled.js@37685023 (dict '2575_02': 'Smart Meter - Address') | high
2600_0 | Auto Charge - Enabled | decompiled.js@37685059 (dict '2600_00': 'Auto Charge - Enabled') | high
2703_0 | Security Features | decompiled.js@37685095 (dict '2703_00': 'Security Features') | high
2720_0 | Certificates Max Chain Length | decompiled.js@37685127 (dict '2720_00': 'Certificates Max Chain Length') | high
2721_0 | Certificates Max Store Length | decompiled.js@37685171 (dict '2721_00': 'Certificates Max Store Length') | high
2722_0 | CPO name | decompiled.js@37685215 (dict '2722_00': 'CPO name') | high
2723_0 | Security Profile | decompiled.js@37685238 (dict '2723_00': 'Security Profile') | high
2724_0 | Max. number of certificates | decompiled.js@37685269 (dict '2724_00': 'Max. number of certificates') | high
2911_0 | Firmware Update Status | decompiled.js@37685311 (dict '2911_00': 'Firmware Update Status') | high
3125_0 | Socket 2 - Socket type | decompiled.js@37685348 (dict '3125_00': 'Socket 2 - Socket type') | high
3129_0 | Socket 2 - Max current (A) | decompiled.js@37685385 (dict '3129_00': 'Socket 2 - Max current (A)') | high
312A_0 | Socket 2 - External Max. Current (A) | decompiled.js@37685426 (dict '312A_00': 'Socket 2 - External Max. Current (A)') | high
312B_0 | Socket 2 - Standard LB Max Current (A) | decompiled.js@37685477 (dict '312B_00': 'Socket 2 - Standard LB Max Current (A)') | high
312C_0 | Socket 2 - Active Max Current (A) | decompiled.js@37685530 (dict '312C_00': 'Socket 2 - Active Max Current (A)') | high
312D_0 | Socket 2 - Active LB Min Current (A) | decompiled.js@37685578 (dict '312D_00': 'Socket 2 - Active LB Min Current (A)') | high
312E_0 | Socket 1 - Max phases | decompiled.js@37685629 (dict '312E_00': 'Socket 1 - Max phases') | high
312F_0 | Socket 2 - Max phases | decompiled.js@37685665 (dict '312F_00': 'Socket 2 - Max phases') | high
3160_0 | Socket 2 - External Min. Current (A) | decompiled.js@37685701 (dict '3160_00': 'Socket 2 - External Min. Current (A)') | high
3173_0 | Socket 2.2 Max current (A) | decompiled.js@37685752 (dict '3173_00': 'Socket 2.2 Max current (A)') | high
3180_0 | NFC-RFID reader 1 version | decompiled.js@37685793 (dict '3180_00': 'NFC-RFID reader 1 version') | high
3181_0 | NFC-RFID reader 2 version | decompiled.js@37685833 (dict '3181_00': 'NFC-RFID reader 2 version') | high
3182_0 | Bootloader version | decompiled.js@37685873 (dict '3182_00': 'Bootloader version') | high
3190_1 | Socket 1 - Device state | decompiled.js@37685906 (dict '3190_01': 'Socket 1 - Device state') | high
3190_2 | Socket 1 - Device state | decompiled.js@37685944 (dict '3190_02': 'Socket 1 - Device state') | high
3191_1 | Socket 2 - Device state | decompiled.js@37685982 (dict '3191_01': 'Socket 2 - Device state') | high
3191_2 | Socket 2 - Device state | decompiled.js@37686020 (dict '3191_02': 'Socket 2 - Device state') | high
3218_0 | Socket 2 - Meter Type | decompiled.js@37686058 (dict '3218_00': 'Socket 2 - Meter Type') | high
3221_3 | Socket 2 - Voltage L1N (V) | decompiled.js@37686094 (dict '3221_03': 'Socket 2 - Voltage L1N (V)') | high
3221_4 | Socket 2 - Voltage L2N (V) | decompiled.js@37686135 (dict '3221_04': 'Socket 2 - Voltage L2N (V)') | high
3221_5 | Socket 2 - Voltage L3N (V) | decompiled.js@37686176 (dict '3221_05': 'Socket 2 - Voltage L3N (V)') | high
3221_6 | Socket 2 - Voltage L1L2 (V) | decompiled.js@37686217 (dict '3221_06': 'Socket 2 - Voltage L1L2 (V)') | high
3221_7 | Socket 2 - Voltage L2L3 (V) | decompiled.js@37686259 (dict '3221_07': 'Socket 2 - Voltage L2L3 (V)') | high
3221_8 | Socket 2 - Voltage L3L1 (V) | decompiled.js@37686301 (dict '3221_08': 'Socket 2 - Voltage L3L1 (V)') | high
3221_9 | Socket 2 - Current N (A) | decompiled.js@37686343 (dict '3221_09': 'Socket 2 - Current N (A)') | high
3221_A | Socket 2 - Current L1 (A) | decompiled.js@37686382 (dict '3221_0A': 'Socket 2 - Current L1 (A)') | high
3221_B | Socket 2 - Current L2 (A) | decompiled.js@37686422 (dict '3221_0B': 'Socket 2 - Current L2 (A)') | high
3221_C | Socket 2 - Current L3 (A) | decompiled.js@37686462 (dict '3221_0C': 'Socket 2 - Current L3 (A)') | high
3221_D | Socket 2 - Current Sum (A) | decompiled.js@37686502 (dict '3221_0D': 'Socket 2 - Current Sum (A)') | high
3221_E | Socket 2 - Cos L1 | decompiled.js@37686543 (dict '3221_0E': 'Socket 2 - Cos L1') | high
3221_F | Socket 2 - Cos L2 | decompiled.js@37686575 (dict '3221_0F': 'Socket 2 - Cos L2') | high
3221_10 | Socket 2 - Cos L3 | decompiled.js@37686607 (dict '3221_10': 'Socket 2 - Cos L3') | high
3221_11 | Socket 2 - Cos Total | decompiled.js@37686639 (dict '3221_11': 'Socket 2 - Cos Total') | high
3221_12 | Socket 2 - Frequency (Hz) | decompiled.js@37686674 (dict '3221_12': 'Socket 2 - Frequency (Hz)') | high
3221_13 | Socket 2 - Power Real L1 (kW) | decompiled.js@37686714 (dict '3221_13': 'Socket 2 - Power Real L1 (kW)') | high
3221_14 | Socket 2 - Power Real L2 (kW) | decompiled.js@37686758 (dict '3221_14': 'Socket 2 - Power Real L2 (kW)') | high
3221_15 | Socket 2 - Power Real L3 (kW) | decompiled.js@37686802 (dict '3221_15': 'Socket 2 - Power Real L3 (kW)') | high
3221_16 | Socket 2 - Power Real Sum (kW) | decompiled.js@37686846 (dict '3221_16': 'Socket 2 - Power Real Sum (kW)') | high
3221_17 | Socket 2 - Power Apperant L1 (kW) | decompiled.js@37686891 (dict '3221_17': 'Socket 2 - Power Apperant L1 (kW)') | high
3221_18 | Socket 2 - Power Apperant L2 (kW) | decompiled.js@37686939 (dict '3221_18': 'Socket 2 - Power Apperant L2 (kW)') | high
3221_19 | Socket 2 - Power Apperant L3 (kW) | decompiled.js@37686987 (dict '3221_19': 'Socket 2 - Power Apperant L3 (kW)') | high
3221_1A | Socket 2 - Power Apperant Sum (kW) | decompiled.js@37687035 (dict '3221_1A': 'Socket 2 - Power Apperant Sum (kW)') | high
3221_1B | Socket 2 - Power Reactive L1 (kW) | decompiled.js@37687084 (dict '3221_1B': 'Socket 2 - Power Reactive L1 (kW)') | high
3221_1C | Socket 2 - Power Reactive L2 (kW) | decompiled.js@37687132 (dict '3221_1C': 'Socket 2 - Power Reactive L2 (kW)') | high
3221_1D | Socket 2 - Power Reactive L3 (kW) | decompiled.js@37687180 (dict '3221_1D': 'Socket 2 - Power Reactive L3 (kW)') | high
3221_1E | Socket 2 - Power Reactive Sum (kW) | decompiled.js@37687228 (dict '3221_1E': 'Socket 2 - Power Reactive Sum (kW)') | high
3221_1F | Socket 2 - Energy Delivered L1 (kWh) | decompiled.js@37687277 (dict '3221_1F': 'Socket 2 - Energy Delivered L1 (kWh)') | high
3221_20 | Socket 2 - Energy Delivered L2 (kWh) | decompiled.js@37687328 (dict '3221_20': 'Socket 2 - Energy Delivered L2 (kWh)') | high
3221_21 | Socket 2 - Energy Delivered L3 (kWh) | decompiled.js@37687379 (dict '3221_21': 'Socket 2 - Energy Delivered L3 (kWh)') | high
3221_22 | Socket 2 - Energy Delivered Sum (kWh) | decompiled.js@37687430 (dict '3221_22': 'Socket 2 - Energy Delivered Sum (kWh)') | high
3221_23 | Socket 2 - Energy Consumed L1 (kWh) | decompiled.js@37687482 (dict '3221_23': 'Socket 2 - Energy Consumed L1 (kWh)') | high
3221_24 | Socket 2 - Energy Consumed L2 (kWh) | decompiled.js@37687532 (dict '3221_24': 'Socket 2 - Energy Consumed L2 (kWh)') | high
3221_25 | Socket 2 - Energy Consumed L3 (kWh) | decompiled.js@37687582 (dict '3221_25': 'Socket 2 - Energy Consumed L3 (kWh)') | high
3221_26 | Socket 2 - Energy Consumed Sum (kWh) | decompiled.js@37687632 (dict '3221_26': 'Socket 2 - Energy Consumed Sum (kWh)') | high
3221_27 | Socket 2 - Energy Apparent L1 | decompiled.js@37687683 (dict '3221_27': 'Socket 2 - Energy Apparent L1') | high
3221_28 | Socket 2 - Energy Apparent L2 | decompiled.js@37687727 (dict '3221_28': 'Socket 2 - Energy Apparent L2') | high
3221_29 | Socket 2 - Energy Apparent L3 | decompiled.js@37687771 (dict '3221_29': 'Socket 2 - Energy Apparent L3') | high
3221_2A | Socket 2 - Energy Apparent Sum | decompiled.js@37687815 (dict '3221_2A': 'Socket 2 - Energy Apparent Sum') | high
3221_2B | Socket 2 - Energy Reactive L1 | decompiled.js@37687860 (dict '3221_2B': 'Socket 2 - Energy Reactive L1') | high
3221_2C | Socket 2 - Energy Reactive L2 | decompiled.js@37687904 (dict '3221_2C': 'Socket 2 - Energy Reactive L2') | high
3221_2D | Socket 2 - Energy Reactive L3 | decompiled.js@37687948 (dict '3221_2D': 'Socket 2 - Energy Reactive L3') | high
3221_2E | Socket 2 - Energy Reactive Sum | decompiled.js@37687992 (dict '3221_2E': 'Socket 2 - Energy Reactive Sum') | high
3258_0 | OCPP - Min status duration (s) | decompiled.js@37688037 (dict '3258_00': 'OCPP - Min status duration (s)') | high
3260_0 | Local List Items per msg | decompiled.js@37688082 (dict '3260_00': 'Local List Items per msg') | high
3260_1 | Display Width (px) | decompiled.js@37688121 (dict '3260_01': 'Display Width (px)') | high
3260_2 | Display Height (px) | decompiled.js@37688154 (dict '3260_02': 'Display Height (px)') | high
3260_3 | Logo Width (px) | decompiled.js@37688188 (dict '3260_03': 'Logo Width (px)') | high
3260_4 | Logo Height (px) | decompiled.js@37688218 (dict '3260_04': 'Logo Height (px)') | high
3260_5 | Max Upload Size (bytes) | decompiled.js@37688249 (dict '3260_05': 'Max Upload Size (bytes)') | high
3261_0 | Display items | decompiled.js@37688287 (dict '3261_00': 'Display items') | high
3262_1 | Currency (ISO 5217) | decompiled.js@37688315 (dict '3262_01': 'Currency (ISO 5217)') | high
3262_2 | Start tariff | decompiled.js@37688349 (dict '3262_02': 'Start tariff') | high
3262_3 | Price per kWh | decompiled.js@37688376 (dict '3262_03': 'Price per kWh') | high
3262_4 | Price per minute | decompiled.js@37688404 (dict '3262_04': 'Price per minute') | high
3262_5 | Show Tariffs | decompiled.js@37688435 (dict '3262_05': 'Show Tariffs') | high
3262_6 | Price Other Tariff | decompiled.js@37688462 (dict '3262_06': 'Price Other Tariff') | high
3262_7 | Price Other Tariff Desciption | decompiled.js@37688495 (dict '3262_07': 'Price Other Tariff Desciption') | high
3263_1 | OCPP - Tariff enabled | decompiled.js@37688539 (dict '3263_01': 'OCPP - Tariff enabled') | high
3263_2 | OCPP - Tariff fallback message | decompiled.js@37688575 (dict '3263_02': 'OCPP - Tariff fallback message') | high
3263_3 | OCPP - Cost enabled | decompiled.js@37688620 (dict '3263_03': 'OCPP - Cost enabled') | high
3263_4 | OCPP - Cost fallback message | decompiled.js@37688654 (dict '3263_04': 'OCPP - Cost fallback message') | high
3263_5 | OCPP - Custom field | decompiled.js@37688697 (dict '3263_05': 'OCPP - Custom field') | high
3264_0 | OCPP - Aligned Transaction Interval | decompiled.js@37688731 (dict '3264_00': 'OCPP - Aligned Transaction Interval') | high
3265_0 | OCPP - Offline Threshold | decompiled.js@37688781 (dict '3265_00': 'OCPP - Offline Threshold') | high
3266_0 | OCPP - Message Timeout | decompiled.js@37688820 (dict '3266_00': 'OCPP - Message Timeout') | high
3267_0 | Local List Entries | decompiled.js@37688857 (dict '3267_00': 'Local List Entries') | high
3269_0 | Local List Bytes per msg | decompiled.js@37688890 (dict '3269_00': 'Local List Bytes per msg') | high
3270_0 | Sampled Transaction Interval | decompiled.js@37688929 (dict '3270_00': 'Sampled Transaction Interval') | high
3271_0 | Sampled Transaction Started Measurands | decompiled.js@37688972 (dict '3271_00': 'Sampled Transaction Started Measurands') | high
3272_0 | Certificate Entries | decompiled.js@37689025 (dict '3272_00': 'Certificate Entries') | high
3273_0 | Rate Units | decompiled.js@37689059 (dict '3273_00': 'Rate Units') | high
3274_0 | Charging Profile Entries | decompiled.js@37689084 (dict '3274_00': 'Charging Profile Entries') | high
3275_0 | Charging Profile Limit Change | decompiled.js@37689123 (dict '3275_00': 'Charging Profile Limit Change') | high
3276_1 | OCPP - DataTime | decompiled.js@37689167 (dict '3276_01': 'OCPP - DataTime') | high
3276_2 | OCPP - NTP Server URL | decompiled.js@37689197 (dict '3276_02': 'OCPP - NTP Server URL') | high
3276_3 | OCPP - NTP Source | decompiled.js@37689233 (dict '3276_03': 'OCPP - NTP Source') | high
3276_4 | OCPP - Time Offset | decompiled.js@37689265 (dict '3276_04': 'OCPP - Time Offset') | high
3276_5 | OCPP - Next Transition DateTime   | decompiled.js@37689298 (dict '3276_05': 'OCPP - Next Transition DateTime  ') | high
3276_6 | OCPP - Next Transition Offset | decompiled.js@37689346 (dict '3276_06': 'OCPP - Next Transition Offset') | high
3276_7 | OCPP - Time Source | decompiled.js@37689390 (dict '3276_07': 'OCPP - Time Source') | high
3276_8 | OCPP - Time Zone | decompiled.js@37689423 (dict '3276_08': 'OCPP - Time Zone') | high
3277_1 | OCPP - Items per GetReport Msg | decompiled.js@37689454 (dict '3277_01': 'OCPP - Items per GetReport Msg') | high
3277_2 | OCPP - Items per GetVariables Msg | decompiled.js@37689499 (dict '3277_02': 'OCPP - Items per GetVariables Msg') | high
3277_3 | OCPP - Items per SetVariables Msg | decompiled.js@37689547 (dict '3277_03': 'OCPP - Items per SetVariables Msg') | high
3277_4 | OCPP - Bytes per GetReport Msg | decompiled.js@37689595 (dict '3277_04': 'OCPP - Bytes per GetReport Msg') | high
3277_5 | OCPP - Bytes per GetVariables Msg | decompiled.js@37689640 (dict '3277_05': 'OCPP - Bytes per GetVariables Msg') | high
3277_6 | OCPP - Bytes per SetVariables Msg | decompiled.js@37689688 (dict '3277_06': 'OCPP - Bytes per SetVariables Msg') | high
3277_7 | OCPP - Configuration Size | decompiled.js@37689736 (dict '3277_07': 'OCPP - Configuration Size') | high
3277_8 | OCPP - Reporting size  | decompiled.js@37689776 (dict '3277_08': 'OCPP - Reporting size ') | high
3278_1 | Override Charging Profile Socket 1 | decompiled.js@37689813 (dict '3278_01': 'Override Charging Profile Socket 1') | high
3278_2 | Override Charging Profile Socket 2 | decompiled.js@37689862 (dict '3278_02': 'Override Charging Profile Socket 2') | high
3280_1 | Solar - Operation Mode | decompiled.js@37689911 (dict '3280_01': 'Solar - Operation Mode') | high
3280_2 | Solar - Green Share | decompiled.js@37689948 (dict '3280_02': 'Solar - Green Share') | high
3280_3 | Solar - Comfort Level | decompiled.js@37689982 (dict '3280_03': 'Solar - Comfort Level') | high
3280_4 | Solar - Override Socket 1 | decompiled.js@37690018 (dict '3280_04': 'Solar - Override Socket 1') | high
3280_5 | Solar - Override Socket 2 | decompiled.js@37690058 (dict '3280_05': 'Solar - Override Socket 2') | high
3284_0 | Wifi - Enabled | decompiled.js@37690098 (dict '3284_00': 'Wifi - Enabled') | high
3285_1 | Wifi - IP Address | decompiled.js@37690127 (dict '3285_01': 'Wifi - IP Address') | high
3285_2 | Wifi - Fixed IP Address | decompiled.js@37690159 (dict '3285_02': 'Wifi - Fixed IP Address') | high
3286_1 | Wifi - Netmask | decompiled.js@37690197 (dict '3286_01': 'Wifi - Netmask') | high
3286_2 | Wifi - Fixed Netmask | decompiled.js@37690226 (dict '3286_02': 'Wifi - Fixed Netmask') | high
3287_1 | Wifi - Gateway | decompiled.js@37690261 (dict '3287_01': 'Wifi - Gateway') | high
3287_2 | Wifi - Fixed Gateway | decompiled.js@37690290 (dict '3287_02': 'Wifi - Fixed Gateway') | high
3288_1 | Wifi - DNS 1 | decompiled.js@37690325 (dict '3288_01': 'Wifi - DNS 1') | high
3288_2 | Wifi - Fixed DNS 1 | decompiled.js@37690352 (dict '3288_02': 'Wifi - Fixed DNS 1') | high
3289_1 | Wifi - DNS 2 | decompiled.js@37690385 (dict '3289_01': 'Wifi - DNS 2') | high
3289_2 | Wifi - Fixed DNS 2 | decompiled.js@37690412 (dict '3289_02': 'Wifi - Fixed DNS 2') | high
328A_0 | Wifi - SSID | decompiled.js@37690445 (dict '328A_00': 'Wifi - SSID') | high
328B_0 | Wifi - Password | decompiled.js@37690471 (dict '328B_00': 'Wifi - Password') | high
328C_0 | Wifi - Security | decompiled.js@37690501 (dict '328C_00': 'Wifi - Security') | high
328D_0 | Wifi - RSSI | decompiled.js@37690531 (dict '328D_00': 'Wifi - RSSI') | high
328E_0 | Wifi - Status | decompiled.js@37690557 (dict '328E_00': 'Wifi - Status') | high
328F_0 | Wifi - Available | decompiled.js@37690585 (dict '328F_00': 'Wifi - Available') | high
3290_0 | Wifi - AP Timeout | decompiled.js@37690616 (dict '3290_00': 'Wifi - AP Timeout') | high
3291_0 | Wifi - AP Enabled | decompiled.js@37690648 (dict '3291_00': 'Wifi - AP Enabled') | high
3293_0 | Wifi - Station Status | decompiled.js@37690680 (dict '3293_00': 'Wifi - Station Status') | high
3294_0 | Wifi - AP Status | decompiled.js@37690716 (dict '3294_00': 'Wifi - AP Status') | high
3550_0 | Backoffice - Connection Type | decompiled.js@37690747 (dict '3550_00': 'Backoffice - Connection Type') | high
3553_0 | Backoffice - Active Profile | decompiled.js@37690790 (dict '3553_00': 'Backoffice - Active Profile') | high
3600_1 | OCPP - Boot state | decompiled.js@37690832 (dict '3600_01': 'OCPP - Boot state') | high
3600_2 | OCPP - Boot Last time send | decompiled.js@37690864 (dict '3600_02': 'OCPP - Boot Last time send') | high
3600_3 | OCPP - Boot Accept Time | decompiled.js@37690905 (dict '3600_03': 'OCPP - Boot Accept Time') | high
3600_4 | OCPP - Boot Delay | decompiled.js@37690943 (dict '3600_04': 'OCPP - Boot Delay') | high
3600_5 | OCPP - RPC Connected | decompiled.js@37690975 (dict '3600_05': 'OCPP - RPC Connected') | high
3600_6 | OCPP - Heartbeat Last received | decompiled.js@37691010 (dict '3600_06': 'OCPP - Heartbeat Last received') | high
3600_7 | OCPP - Heartbeat Last failed | decompiled.js@37691055 (dict '3600_07': 'OCPP - Heartbeat Last failed') | high
3600_8 | OCPP - Heartbeat Last sent | decompiled.js@37691098 (dict '3600_08': 'OCPP - Heartbeat Last sent') | high
4217_0 | Protocol selection | decompiled.js@37691139 (dict '4217_00': 'Protocol selection') | high
4218_0 | Modbus type | decompiled.js@37691172 (dict '4218_00': 'Modbus type') | high
4221_3 | Central Meter - Voltage L1N (V) | decompiled.js@37691198 (dict '4221_03': 'Central Meter - Voltage L1N (V)') | high
4221_4 | Central Meter  - Voltage L2N (V) | decompiled.js@37691244 (dict '4221_04': 'Central Meter  - Voltage L2N (V)') | high
4221_5 | Central Meter  - Voltage L3N (V) | decompiled.js@37691291 (dict '4221_05': 'Central Meter  - Voltage L3N (V)') | high
4221_6 | Central Meter  - Voltage L1L2 (V) | decompiled.js@37691338 (dict '4221_06': 'Central Meter  - Voltage L1L2 (V)') | high
4221_7 | Central Meter  - Voltage L2L3 (V) | decompiled.js@37691386 (dict '4221_07': 'Central Meter  - Voltage L2L3 (V)') | high
4221_8 | Central Meter - Voltage L3L1 (V) | decompiled.js@37691434 (dict '4221_08': 'Central Meter - Voltage L3L1 (V)') | high
4221_9 | Central Meter - Current N (A) | decompiled.js@37691481 (dict '4221_09': 'Central Meter - Current N (A)') | high
4221_A | Central Meter - Current L1 (A) | decompiled.js@37691525 (dict '4221_0A': 'Central Meter - Current L1 (A)') | high
4221_B | Central Meter - Current L2 (A) | decompiled.js@37691570 (dict '4221_0B': 'Central Meter - Current L2 (A)') | high
4221_C | Central Meter - Current L3 (A) | decompiled.js@37691615 (dict '4221_0C': 'Central Meter - Current L3 (A)') | high
4221_D | Central Meter - Current Sum (A) | decompiled.js@37691660 (dict '4221_0D': 'Central Meter - Current Sum (A)') | high
4221_E | Central meter - Cos L1 | decompiled.js@37691706 (dict '4221_0E': 'Central meter - Cos L1') | high
4221_F | Central meter - Cos L2 | decompiled.js@37691743 (dict '4221_0F': 'Central meter - Cos L2') | high
4221_10 | Central meter - Cos L3 | decompiled.js@37691780 (dict '4221_10': 'Central meter - Cos L3') | high
4221_11 | Central meter - Cos Total | decompiled.js@37691817 (dict '4221_11': 'Central meter - Cos Total') | high
4221_12 | Central meter - Frequency (Hz) | decompiled.js@37691857 (dict '4221_12': 'Central meter - Frequency (Hz)') | high
4221_13 | Central meter - Power Real L1 (kW) | decompiled.js@37691902 (dict '4221_13': 'Central meter - Power Real L1 (kW)') | high
4221_14 | Central meter - Power Real L2 (kW) | decompiled.js@37691951 (dict '4221_14': 'Central meter - Power Real L2 (kW)') | high
4221_15 | Central meter - Power Real L3 (kW) | decompiled.js@37692000 (dict '4221_15': 'Central meter - Power Real L3 (kW)') | high
4221_16 | Central meter - Power Real Sum (kW) | decompiled.js@37692049 (dict '4221_16': 'Central meter - Power Real Sum (kW)') | high
4221_17 | Central meter - Power Apperant L1 (kW) | decompiled.js@37692099 (dict '4221_17': 'Central meter - Power Apperant L1 (kW)') | high
4221_18 | Central meter - Power Apperant L2 (kW) | decompiled.js@37692152 (dict '4221_18': 'Central meter - Power Apperant L2 (kW)') | high
4221_19 | Central meter - Power Apperant L3 (kW) | decompiled.js@37692205 (dict '4221_19': 'Central meter - Power Apperant L3 (kW)') | high
4221_1A | Central meter - Power Apperant Sum (kW) | decompiled.js@37692258 (dict '4221_1A': 'Central meter - Power Apperant Sum (kW)') | high
4221_1B | Central meter - Power Reactive L1 (kW) | decompiled.js@37692312 (dict '4221_1B': 'Central meter - Power Reactive L1 (kW)') | high
4221_1C | Central meter - Power Reactive L2 (kW) | decompiled.js@37692365 (dict '4221_1C': 'Central meter - Power Reactive L2 (kW)') | high
4221_1D | Central meter - Power Reactive L3 (kW) | decompiled.js@37692418 (dict '4221_1D': 'Central meter - Power Reactive L3 (kW)') | high
4221_1E | Central meter - Power Reactive Sum (kW) | decompiled.js@37692471 (dict '4221_1E': 'Central meter - Power Reactive Sum (kW)') | high
4221_1F | Central meter - Energy Delivered L1 (kWh) | decompiled.js@37692525 (dict '4221_1F': 'Central meter - Energy Delivered L1 (kWh)') | high
4221_20 | Central meter - Energy Delivered L2 (kWh) | decompiled.js@37692581 (dict '4221_20': 'Central meter - Energy Delivered L2 (kWh)') | high
4221_21 | Central meter - Energy Delivered L3 (kWh) | decompiled.js@37692637 (dict '4221_21': 'Central meter - Energy Delivered L3 (kWh)') | high
4221_22 | Central meter - Energy Delivered Sum (kWh) | decompiled.js@37692693 (dict '4221_22': 'Central meter - Energy Delivered Sum (kWh)') | high
4221_23 | Central meter - Energy Consumed L1 (kWh) | decompiled.js@37692750 (dict '4221_23': 'Central meter - Energy Consumed L1 (kWh)') | high
4221_24 | Central meter - Energy Consumed L2 (kWh) | decompiled.js@37692805 (dict '4221_24': 'Central meter - Energy Consumed L2 (kWh)') | high
4221_25 | Central meter - Energy Consumed L3 (kWh) | decompiled.js@37692860 (dict '4221_25': 'Central meter - Energy Consumed L3 (kWh)') | high
4221_26 | Cenral meter - Energy Consumed Sum (kWh) | decompiled.js@37692915 (dict '4221_26': 'Cenral meter - Energy Consumed Sum (kWh)') | high
4221_27 | Central meter - Energy Apparent L1 | decompiled.js@37692970 (dict '4221_27': 'Central meter - Energy Apparent L1') | high
4221_28 | Central meter - Energy Apparent L2 | decompiled.js@37693019 (dict '4221_28': 'Central meter - Energy Apparent L2') | high
4221_29 | Central meter - Energy Apparent L3 | decompiled.js@37693068 (dict '4221_29': 'Central meter - Energy Apparent L3') | high
4221_2A | Central meter - Energy Apparent Sum | decompiled.js@37693117 (dict '4221_2A': 'Central meter - Energy Apparent Sum') | high
4221_2B | Central meter - Energy Reactive L1 | decompiled.js@37693167 (dict '4221_2B': 'Central meter - Energy Reactive L1') | high
4221_2C | Central meter - Energy Reactive L2 | decompiled.js@37693216 (dict '4221_2C': 'Central meter - Energy Reactive L2') | high
4221_2D | Central meter - Energy Reactive L3 | decompiled.js@37693265 (dict '4221_2D': 'Central meter - Energy Reactive L3') | high
4221_2E | Central meter - Energy Reactive Sum | decompiled.js@37693314 (dict '4221_2E': 'Central meter - Energy Reactive Sum') | high
5217_0 | Smart Meter - Protocol selection | decompiled.js@37693364 (dict '5217_00': 'Smart Meter - Protocol selection') | high
5218_0 | Smart Meter - Meter type | decompiled.js@37693411 (dict '5218_00': 'Smart Meter - Meter type') | high
5221_3 | Smart Meter - Voltage L1N (V) | decompiled.js@37693450 (dict '5221_03': 'Smart Meter - Voltage L1N (V)') | high
5221_4 | Smart Meter  - Voltage L2N (V) | decompiled.js@37693494 (dict '5221_04': 'Smart Meter  - Voltage L2N (V)') | high
5221_5 | Smart Meter  - Voltage L3N (V) | decompiled.js@37693539 (dict '5221_05': 'Smart Meter  - Voltage L3N (V)') | high
5221_6 | Smart Meter  - Voltage L1L2 (V) | decompiled.js@37693584 (dict '5221_06': 'Smart Meter  - Voltage L1L2 (V)') | high
5221_7 | Smart Meter  - Voltage L2L3 (V) | decompiled.js@37693630 (dict '5221_07': 'Smart Meter  - Voltage L2L3 (V)') | high
5221_8 | Smart Meter - Voltage L3L1 (V) | decompiled.js@37693676 (dict '5221_08': 'Smart Meter - Voltage L3L1 (V)') | high
5221_9 | Smart Meter - Current N (A) | decompiled.js@37693721 (dict '5221_09': 'Smart Meter - Current N (A)') | high
5221_A | Smart Meter - Current L1 (A) | decompiled.js@37693763 (dict '5221_0A': 'Smart Meter - Current L1 (A)') | high
5221_B | Smart Meter - Current L2 (A) | decompiled.js@37693806 (dict '5221_0B': 'Smart Meter - Current L2 (A)') | high
5221_C | Smart Meter - Current L3 (A) | decompiled.js@37693849 (dict '5221_0C': 'Smart Meter - Current L3 (A)') | high
5221_D | Smart Meter - Current Sum (A) | decompiled.js@37693892 (dict '5221_0D': 'Smart Meter - Current Sum (A)') | high
5221_E | Smart meter - Cos L1 | decompiled.js@37693936 (dict '5221_0E': 'Smart meter - Cos L1') | high
5221_F | Smart meter - Cos L2 | decompiled.js@37693971 (dict '5221_0F': 'Smart meter - Cos L2') | high
5221_10 | Smart meter - Cos L3 | decompiled.js@37694006 (dict '5221_10': 'Smart meter - Cos L3') | high
5221_11 | Smart meter - Cos Sum | decompiled.js@37694041 (dict '5221_11': 'Smart meter - Cos Sum') | high
5221_12 | Smart meter - Frequency (Hz) | decompiled.js@37694077 (dict '5221_12': 'Smart meter - Frequency (Hz)') | high
5221_13 | Smart meter - Power Real L1 (kW) | decompiled.js@37694120 (dict '5221_13': 'Smart meter - Power Real L1 (kW)') | high
5221_14 | Smart meter - Power Real L2 (kW) | decompiled.js@37694167 (dict '5221_14': 'Smart meter - Power Real L2 (kW)') | high
5221_15 | Smart meter - Power Real L3 (kW) | decompiled.js@37694214 (dict '5221_15': 'Smart meter - Power Real L3 (kW)') | high
5221_16 | Smart meter - Power Real Sum (kW) | decompiled.js@37694261 (dict '5221_16': 'Smart meter - Power Real Sum (kW)') | high
5221_17 | Smart meter - Power Apperant L1 (kW) | decompiled.js@37694309 (dict '5221_17': 'Smart meter - Power Apperant L1 (kW)') | high
5221_18 | Smart meter - Power Apperant L2 (kW) | decompiled.js@37694360 (dict '5221_18': 'Smart meter - Power Apperant L2 (kW)') | high
5221_19 | Smart meter - Power Apperant L3 (kW) | decompiled.js@37694411 (dict '5221_19': 'Smart meter - Power Apperant L3 (kW)') | high
5221_1A | Smart meter - Power Apperant Sum (kW) | decompiled.js@37694462 (dict '5221_1A': 'Smart meter - Power Apperant Sum (kW)') | high
5221_1B | Smart meter - Power Reactive L1 (kW) | decompiled.js@37694514 (dict '5221_1B': 'Smart meter - Power Reactive L1 (kW)') | high
5221_1C | Smart meter - Power Reactive L2 (kW) | decompiled.js@37694565 (dict '5221_1C': 'Smart meter - Power Reactive L2 (kW)') | high
5221_1D | Smart meter - Power Reactive L3 (kW) | decompiled.js@37694616 (dict '5221_1D': 'Smart meter - Power Reactive L3 (kW)') | high
5221_1E | Smart meter - Power Reactive Sum (kW) | decompiled.js@37694667 (dict '5221_1E': 'Smart meter - Power Reactive Sum (kW)') | high
5221_1F | Smart meter - Energy Delivered L1 (kWh) | decompiled.js@37694719 (dict '5221_1F': 'Smart meter - Energy Delivered L1 (kWh)') | high
5221_20 | Smart meter - Energy Delivered L2 (kWh) | decompiled.js@37694773 (dict '5221_20': 'Smart meter - Energy Delivered L2 (kWh)') | high
5221_21 | Smart meter - Energy Delivered L3 (kWh) | decompiled.js@37694827 (dict '5221_21': 'Smart meter - Energy Delivered L3 (kWh)') | high
5221_22 | Smart meter - Energy Delivered Sum (kWh) | decompiled.js@37694881 (dict '5221_22': 'Smart meter - Energy Delivered Sum (kWh)') | high
5221_23 | Smart meter - Energy Consumed L1 (kWh) | decompiled.js@37694936 (dict '5221_23': 'Smart meter - Energy Consumed L1 (kWh)') | high
5221_24 | Smart meter - Energy Consumed L2 (kWh) | decompiled.js@37694989 (dict '5221_24': 'Smart meter - Energy Consumed L2 (kWh)') | high
5221_25 | Smart meter - Energy Consumed L3 (kWh) | decompiled.js@37695042 (dict '5221_25': 'Smart meter - Energy Consumed L3 (kWh)') | high
5221_26 | Smart meter - Energy Consumed Sum (kWh) | decompiled.js@37695095 (dict '5221_26': 'Smart meter - Energy Consumed Sum (kWh)') | high
5221_27 | Smart meter - Energy Apparent L1 | decompiled.js@37695149 (dict '5221_27': 'Smart meter - Energy Apparent L1') | high
5221_28 | Smart meter - Energy Apparent L2 | decompiled.js@37695196 (dict '5221_28': 'Smart meter - Energy Apparent L2') | high
5221_29 | Smart meter - Energy Apparent L3 | decompiled.js@37695243 (dict '5221_29': 'Smart meter - Energy Apparent L3') | high
5221_2A | Smart meter - Energy Apparent Sum | decompiled.js@37695290 (dict '5221_2A': 'Smart meter - Energy Apparent Sum') | high
5221_2B | Smart meter - Energy Reactive L1 | decompiled.js@37695338 (dict '5221_2B': 'Smart meter - Energy Reactive L1') | high
5221_2C | Smart meter - Energy Reactive L2 | decompiled.js@37695385 (dict '5221_2C': 'Smart meter - Energy Reactive L2') | high
5221_2D | Smart meter - Energy Reactive L3 | decompiled.js@37695432 (dict '5221_2D': 'Smart meter - Energy Reactive L3') | high
5221_2E | Smart meter - Energy Reactive Sum | decompiled.js@37695479 (dict '5221_2E': 'Smart meter - Energy Reactive Sum') | high
5230_0 | Register Meter values incl. Phases | decompiled.js@37695527 (dict '5230_00': 'Register Meter values incl. Phases') | high
8006_0 | Display ID - 0 for device without | decompiled.js@37695576 (dict '8006_00': 'Display ID - 0 for device without') | high
8101_1 | Device ID - Socket Board 1 | decompiled.js@37695624 (dict '8101_01': 'Device ID - Socket Board 1') | high
8101_2 | Device ID - Socket Board 2 | decompiled.js@37695665 (dict '8101_02': 'Device ID - Socket Board 2') | high
8102_1 | Hardware Version - Socket Board 1 | decompiled.js@37695706 (dict '8102_01': 'Hardware Version - Socket Board 1') | high
8102_2 | Hardware Version - Socket Board 2 | decompiled.js@37695754 (dict '8102_02': 'Hardware Version - Socket Board 2') | high
8103_1 | Software Version - Socket Board 1 | decompiled.js@37695802 (dict '8103_01': 'Software Version - Socket Board 1') | high
8103_2 | Software Version - Socket Board 2 | decompiled.js@37695850 (dict '8103_02': 'Software Version - Socket Board 2') | high
8107_1 | ISO15118 SW - Socket Board 1 | decompiled.js@37695986 (dict '8107_01': 'ISO15118 SW - Socket Board 1') | high
8107_2 | IS015118 SW - Socket Board 2 | decompiled.js@37696029 (dict '8107_02': 'IS015118 SW - Socket Board 2') | high
8108_1 | Energy Meter - Socket Board 1 | decompiled.js@37695898 (dict '8108_01': 'Energy Meter - Socket Board 1') | high
8108_2 | Energy Meter - Socket Board 2 | decompiled.js@37695942 (dict '8108_02': 'Energy Meter - Socket Board 2') | high
8109_1 | ISO15118 HW - Socket Board 1 | decompiled.js@37696158 (dict '8109_01': 'ISO15118 HW - Socket Board 1') | high
8109_2 | ISO15118 HW - Socket Board 2 | decompiled.js@37696201 (dict '8109_02': 'ISO15118 HW - Socket Board 2') | high
810A_1 | Socket Type - Socket Board 1 | decompiled.js@37696072 (dict '810A_01': 'Socket Type - Socket Board 1') | high
810A_2 | Socket Type - Socket Board 2 | decompiled.js@37696115 (dict '810A_02': 'Socket Type - Socket Board 2') | high
8201_0 | Device ID - NFC | decompiled.js@37696244 (dict '8201_00': 'Device ID - NFC') | high
8202_0 | Hardware version - NFC | decompiled.js@37696274 (dict '8202_00': 'Hardware version - NFC') | high
8203_0 | Software version - NFC | decompiled.js@37696311 (dict '8203_00': 'Software version - NFC') | high
8301_0 | DC charger - CS max. current (A) | decompiled.js@37696348 (dict '8301_00': 'DC charger - CS max. current (A)') | high
8302_0 | DC charger - Socket 1 max. current (A) | decompiled.js@37696395 (dict '8302_00': 'DC charger - Socket 1 max. current (A)') | high
8303_0 | DC charger - Socket 2 max. current (A) | decompiled.js@37696448 (dict '8303_00': 'DC charger - Socket 2 max. current (A)') | high

## Validation rules / type hints (from embedded rules module, decompiled.js ~36072253–36302601)

Module builds `{defaultValue, rule:{min,max,type}, formRule}` per writable property. `type` values:
numeric/string/boolean (PropRuleType). Extracted for 211 properties (all writable form fields).
min/max are signed 32-bit (e.g. latitude min -90). Register-carried defaults marked `rN` where unresolvable.

id | type | min | max | default | formRule | evidence
2053_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2053_00')
205C_1 | numeric | -90 | 90 | r12 | None | decompiled.js@~36072253-36302601 (rules module, key '205C_01')
205C_2 | numeric | -180 | 180 | r12 | None | decompiled.js@~36072253-36302601 (rules module, key '205C_02')
205D_0 | None | None | None | r12 | None | decompiled.js@~36072253-36302601 (rules module, key '205D_00')
205F_0 | numeric | 0 | 8 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '205F_00')
2061_1 | numeric | 0 | 8 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2061_01')
2061_2 | numeric | 0 | 100 | 75 | None | decompiled.js@~36072253-36302601 (rules module, key '2061_02')
2062_0 | numeric | 1 | 64 | 16 | None | decompiled.js@~36072253-36302601 (rules module, key '2062_00')
2063_0 | string | 8 | 20 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2063_00')
2067_0 | numeric | 10 | 5000 | 25 | None | decompiled.js@~36072253-36302601 (rules module, key '2067_00')
2068_0 | numeric | 6 | 100 | r14 | None | decompiled.js@~36072253-36302601 (rules module, key '2068_00')
2069_0 | None | None | None | 'L1L2L3' | None | decompiled.js@~36072253-36302601 (rules module, key '2069_00')
206A_0 | numeric | 1 | 100 | 14 | None | decompiled.js@~36072253-36302601 (rules module, key '206A_00')
206B_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '206B_01')
206B_2 | None | None | None | 60 | None | decompiled.js@~36072253-36302601 (rules module, key '206B_02')
206B_3 | None | None | None | r27 | None | decompiled.js@~36072253-36302601 (rules module, key '206B_03')
206C_1 | numeric | 0 | 5 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '206C_01')
206E_0 | numeric | -720 | 780 | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '206E_00')
206F_0 | None | None | None | r21 | None | decompiled.js@~36072253-36302601 (rules module, key '206F_00')
2070_0 | None | None | None | 4 | None | decompiled.js@~36072253-36302601 (rules module, key '2070_00')
2071_1 | string | 0 | 63 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2071_01')
2071_2 | string | 0 | 63 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2071_02')
2072_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2072_01')
2072_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2072_02')
2073_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2073_01')
2074_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2074_01')
2075_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2075_01')
2075_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2075_02')
2076_0 | string | 0 | 49 | r21 | None | decompiled.js@~36072253-36302601 (rules module, key '2076_00')
2077_0 | None | None | None | r21 | None | decompiled.js@~36072253-36302601 (rules module, key '2077_00')
2078_1 | string | 0 | 63 | 'ws://icuconnect.nl:9090' | None | decompiled.js@~36072253-36302601 (rules module, key '2078_01')
2078_2 | string | 0 | 63 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2078_02')
2079_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2079_01')
2079_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2079_02')
207A_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207A_01')
207A_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207A_02')
207B_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207B_01')
207C_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207C_01')
207D_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207D_01')
207D_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207D_02')
207E_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207E_01')
207E_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207E_02')
207F_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207F_01')
207F_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '207F_02')
2080_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2080_01')
2080_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2080_02')
2081_0 | string | 0 | 20 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2081_00')
2082_0 | None | None | None | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2082_00')
2086_0 | None | None | None | None | required | decompiled.js@~36072253-36302601 (rules module, key '2086_00')
2087_0 | None | None | None | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2087_00')
2088_0 | None | None | None | r28 | None | decompiled.js@~36072253-36302601 (rules module, key '2088_00')
2089_0 | None | None | None | r25 | None | decompiled.js@~36072253-36302601 (rules module, key '2089_00')
208A_0 | None | None | None | 120 | None | decompiled.js@~36072253-36302601 (rules module, key '208A_00')
208B_1 | None | None | None | r22 | None | decompiled.js@~36072253-36302601 (rules module, key '208B_01')
208B_2 | None | None | None | 15 | None | decompiled.js@~36072253-36302601 (rules module, key '208B_02')
208D_1 | None | None | None | r18 | None | decompiled.js@~36072253-36302601 (rules module, key '208D_01')
208D_2 | None | None | None | 50 | None | decompiled.js@~36072253-36302601 (rules module, key '208D_02')
208E_1 | None | None | None | r27 | None | decompiled.js@~36072253-36302601 (rules module, key '208E_01')
208E_2 | None | None | None | r28 | None | decompiled.js@~36072253-36302601 (rules module, key '208E_02')
208F_0 | None | None | None | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '208F_00')
2093_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2093_00')
2094_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2094_00')
2095_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2095_00')
2096_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2096_00')
2097_0 | None | None | None | r17 | None | decompiled.js@~36072253-36302601 (rules module, key '2097_00')
209A_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '209A_00')
209B_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '209B_00')
209C_0 | None | None | None | r12 | None | decompiled.js@~36072253-36302601 (rules module, key '209C_00')
209D_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '209D_00')
2100_0 | string | 0 | 31 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2100_00')
2101_0 | string | 0 | 31 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2101_00')
2102_0 | string | 0 | 31 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2102_00')
2103_0 | string | 0 | 21 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2103_00')
2106_0 | string | 0 | 128 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2106_00')
2107_0 | numeric | 1 | 128 | r18 | None | decompiled.js@~36072253-36302601 (rules module, key '2107_00')
2108_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2108_00')
2111_0 | None | None | None | r29 | None | decompiled.js@~36072253-36302601 (rules module, key '2111_00')
2113_0 | None | None | None | r30 | None | decompiled.js@~36072253-36302601 (rules module, key '2113_00')
2114_0 | None | None | None | r29 | None | decompiled.js@~36072253-36302601 (rules module, key '2114_00')
2115_0 | string | 0 | 63 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2115_00')
2116_0 | string | 0 | 31 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2116_00')
2117_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2117_00')
2124_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2124_00')
2125_0 | None | None | None | r29 | None | decompiled.js@~36072253-36302601 (rules module, key '2125_00')
2126_0 | None | None | None | 11 | None | decompiled.js@~36072253-36302601 (rules module, key '2126_00')
2127_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2127_00')
2128_0 | numeric | 0 | 32 | r14 | None | decompiled.js@~36072253-36302601 (rules module, key '2128_00')
2129_0 | numeric | 6 | 32 | None | required | decompiled.js@~36072253-36302601 (rules module, key '2129_00')
2130_0 | numeric | 0 | 32 | r14 | None | decompiled.js@~36072253-36302601 (rules module, key '2130_00')
2131_0 | numeric | 0 | 128 | r18 | None | decompiled.js@~36072253-36302601 (rules module, key '2131_00')
2132_0 | None | None | None | r21 | None | decompiled.js@~36072253-36302601 (rules module, key '2132_00')
2133_0 | None | None | None | 300 | None | decompiled.js@~36072253-36302601 (rules module, key '2133_00')
2134_0 | None | None | None | r17 | None | decompiled.js@~36072253-36302601 (rules module, key '2134_00')
2135_0 | None | None | None | r28 | None | decompiled.js@~36072253-36302601 (rules module, key '2135_00')
2136_0 | None | None | None | r23 | None | decompiled.js@~36072253-36302601 (rules module, key '2136_00')
2137_0 | None | None | None | 12 | None | decompiled.js@~36072253-36302601 (rules module, key '2137_00')
213B_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '213B_00')
213C_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '213C_00')
213D_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '213D_00')
213E_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '213E_00')
2140_0 | None | None | None | 2000 | None | decompiled.js@~36072253-36302601 (rules module, key '2140_00')
2153_0 | numeric | 6 | 8 | r26 | None | decompiled.js@~36072253-36302601 (rules module, key '2153_00')
2159_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2159_00')
215D_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '215D_00')
215E_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '215E_00')
2168_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2168_00')
2169_0 | numeric | 0 | 3600 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2169_00')
216A_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '216A_00')
216B_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '216B_00')
216C_0 | None | None | None | 13 | None | decompiled.js@~36072253-36302601 (rules module, key '216C_00')
216D_0 | numeric | 0 | 59 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '216D_00')
216F_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '216F_00')
2171_0 | None | None | None | r28 | None | decompiled.js@~36072253-36302601 (rules module, key '2171_00')
2172_0 | numeric | 0 | 100 | r27 | None | decompiled.js@~36072253-36302601 (rules module, key '2172_00')
2173_0 | numeric | 1 | 16 | r14 | None | decompiled.js@~36072253-36302601 (rules module, key '2173_00')
2174_0 | numeric | 0 | 5000 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2174_00')
2177_0 | string | 0 | 223 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2177_00')
2178_0 | string | 0 | 223 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2178_00')
2179_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2179_00')
2180_1 | string | 4 | 7 | 'SCN1' | None | decompiled.js@~36072253-36302601 (rules module, key '2180_01')
2180_2 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_02')
2180_3 | None | None | None | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_03')
2180_4 | numeric | 900 | 36000 | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_04')
2180_5 | numeric | 1 | 5000 | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_05')
2180_6 | numeric | 6 | 32 | r26 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_06')
2180_7 | None | None | None | r26 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_07')
2180_9 | None | None | None | r25 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_09')
2180_A | numeric | 1 | 5000 | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '2180_0A')
2182_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2182_00')
2183_0 | numeric | 0 | 2 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2183_00')
2184_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2184_00')
2185_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2185_00')
2187_0 | numeric | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2187_00')
2188_0 | None | None | None | r25 | None | decompiled.js@~36072253-36302601 (rules module, key '2188_00')
2189_0 | numeric | 1 | 3 | r9 | None | decompiled.js@~36072253-36302601 (rules module, key '2189_00')
2190_0 | None | None | None | r24 | None | decompiled.js@~36072253-36302601 (rules module, key '2190_00')
2191_1 | None | None | None | 24 | None | decompiled.js@~36072253-36302601 (rules module, key '2191_01')
2191_2 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2191_02')
2191_3 | numeric | 0 | 65535 | None | required | decompiled.js@~36072253-36302601 (rules module, key '2191_03')
2192_0 | None | None | None | 17 | None | decompiled.js@~36072253-36302601 (rules module, key '2192_00')
21A1_0 | string | 0 | 30 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '21A1_00')
21B0_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '21B0_00')
21B1_0 | None | None | None | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '21B1_00')
21B5_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '21B5_00')
21B9_0 | numeric | 0 | 3600 | 600 | None | decompiled.js@~36072253-36302601 (rules module, key '21B9_00')
2200_0 | None | None | None | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '2200_00')
2202_0 | numeric | -255 | 255 | r23 | None | decompiled.js@~36072253-36302601 (rules module, key '2202_00')
2203_0 | None | None | None | 80 | None | decompiled.js@~36072253-36302601 (rules module, key '2203_00')
2204_0 | None | None | None | r22 | None | decompiled.js@~36072253-36302601 (rules module, key '2204_00')
2205_0 | None | None | None | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2205_00')
2206_0 | None | None | None | 18 | None | decompiled.js@~36072253-36302601 (rules module, key '2206_00')
2207_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2207_00')
2208_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2208_00')
2209_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2209_00')
2210_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2210_00')
2211_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2211_00')
2212_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2212_00')
2213_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2213_00')
2214_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2214_00')
2215_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2215_00')
2216_0 | numeric | 0 | 3600 | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2216_00')
2218_0 | None | None | None | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2218_00')
2400_1 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2400_01')
2400_2 | hexadecimal | 8 | 20 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2400_02')
2401_0 | hexadecimal | 8 | 36 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2401_00')
2522_2 | None | None | None | r20 | None | decompiled.js@~36072253-36302601 (rules module, key '2522_02')
2522_4 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2522_04')
2522_6 | None | None | None | r18 | None | decompiled.js@~36072253-36302601 (rules module, key '2522_06')
2523_2 | None | None | None | r19 | None | decompiled.js@~36072253-36302601 (rules module, key '2523_02')
2523_4 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2523_04')
2523_6 | None | None | None | r18 | None | decompiled.js@~36072253-36302601 (rules module, key '2523_06')
2530_1 | None | None | None | r18 | None | decompiled.js@~36072253-36302601 (rules module, key '2530_01')
2530_2 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2530_02')
2530_3 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2530_03')
2530_4 | None | None | None | r17 | None | decompiled.js@~36072253-36302601 (rules module, key '2530_04')
2571_0 | string | 1 | 49 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2571_00')
2572_0 | string | 1 | 49 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2572_00')
2573_0 | string | 1 | 49 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2573_00')
2574_0 | numeric | 0 | 1 | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '2574_00')
2574_1 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2574_01')
2574_2 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2574_02')
2574_3 | numeric | 1 | 16 | r15 | None | decompiled.js@~36072253-36302601 (rules module, key '2574_03')
2575_0 | None | None | None | 19200 | None | decompiled.js@~36072253-36302601 (rules module, key '2575_00')
2575_1 | numeric | 0 | 2 | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '2575_01')
2575_2 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2575_02')
2600_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '2600_00')
2703_0 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2703_00')
2722_0 | string | 0 | 49 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '2722_00')
2723_0 | numeric | 0 | 3 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2723_00')
2911_0 | numeric | 0 | 12 | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '2911_00')
3129_0 | numeric | 6 | 32 | None | required | decompiled.js@~36072253-36302601 (rules module, key '3129_00')
3173_0 | numeric | 1 | 16 | r14 | None | decompiled.js@~36072253-36302601 (rules module, key '3173_00')
3218_0 | None | None | None | r14 | None | decompiled.js@~36072253-36302601 (rules module, key '3218_00')
3261_0 | None | None | None | r13 | None | decompiled.js@~36072253-36302601 (rules module, key '3261_00')
3262_1 | None | None | None | r12 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_01')
3262_2 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_02')
3262_3 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_03')
3262_4 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_04')
3262_5 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_05')
3262_6 | None | None | None | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_06')
3262_7 | string | 0 | 31 | r11 | None | decompiled.js@~36072253-36302601 (rules module, key '3262_07')
3280_1 | None | None | None | 22 | None | decompiled.js@~36072253-36302601 (rules module, key '3280_01')
3280_2 | None | None | None | r5 | None | decompiled.js@~36072253-36302601 (rules module, key '3280_02')
3280_3 | None | None | None | r10 | None | decompiled.js@~36072253-36302601 (rules module, key '3280_03')
3280_4 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '3280_04')
3280_5 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '3280_05')
4217_0 | None | None | None | 23 | None | decompiled.js@~36072253-36302601 (rules module, key '4217_00')
4218_0 | None | None | None | r10 | None | decompiled.js@~36072253-36302601 (rules module, key '4218_00')
5217_0 | None | None | None | r10 | None | decompiled.js@~36072253-36302601 (rules module, key '5217_00')
5218_0 | None | None | None | r9 | None | decompiled.js@~36072253-36302601 (rules module, key '5218_00')
5230_0 | None | None | None | None | None | decompiled.js@~36072253-36302601 (rules module, key '5230_00')

## Enum / option maps (value -> label)

### i18n descriptor families (from embedded i18n dictionary, decompiled.js ~17870000–17955000 for en)

#### AuthorizationMode
AuthorizationMode | RFID | RFID | decompiled.js@17831097 | high
AuthorizationMode | plugAndCharge | Plug and Charge | decompiled.js@17831043 | high

#### BOProfile
BOProfile | default | 0: Default | decompiled.js@17835910 | high
BOProfile | TLSwithBasicAuthentication | 2: TLS with Basic Authentication | decompiled.js@17835945 | high
BOProfile | TLSwithClientsideCertification | 3: TLS with Client side Certification | decompiled.js@17836021 | high
BOProfile | unsecuretransportwithBasicAuthenticator | 1: Unsecure transport with Basic Authentication | decompiled.js@17836106 | high

#### ConnectorStatusDescriptors
ConnectorStatusDescriptors | Operative | Operative | decompiled.js@17873307 | high
ConnectorStatusDescriptors | InOperative | In-Operative | decompiled.js@17873249 | high

#### ConnectorType
ConnectorType | fct | FCT | decompiled.js@17873408 | high
ConnectorType | schuko | Schuko | decompiled.js@17873594 | high
ConnectorType | balzMennekes | Balz/ Mennekes | decompiled.js@17873360 | high
ConnectorType | fixedCableType1 | Fixed cable type1 | decompiled.js@17873436 | high
ConnectorType | fixedCableType2 | Fixed cable type2 | decompiled.js@17873490 | high
ConnectorType | fixedCableUnknown | Fixed Cable | decompiled.js@17873544 | high

#### DataSource
DataSource | none | None | decompiled.js@17874318 | high
DataSource | smartMeter | Smart Meter | decompiled.js@17874345 | high

#### DeviceStateDescriptors
DeviceStateDescriptors | 000 | 000: Installation OK | decompiled.js@17874626 | high
DeviceStateDescriptors | 001 | 001: Not able to charge. Please call for support | decompiled.js@17874680 | high
DeviceStateDescriptors | 101 | 101: One moment please... Your charging session will resume shortly | decompiled.js@17874762 | high
DeviceStateDescriptors | 102 | 102: Not able to charge. Please call for support | decompiled.js@17874863 | high
DeviceStateDescriptors | 104 | 104: Not able to charge. Please call for support | decompiled.js@17874945 | high
DeviceStateDescriptors | 105 | 105: Not able to charge. Please call for support | decompiled.js@17875027 | high
DeviceStateDescriptors | 106 | 106: Not able to charge. Please call for support | decompiled.js@17875109 | high
DeviceStateDescriptors | 107 | 107: Not able to lock cable. Please call for support | decompiled.js@17875191 | high
DeviceStateDescriptors | 108 | 108 | decompiled.js@17875277 | high
DeviceStateDescriptors | 109 | 109 | decompiled.js@17875314 | high
DeviceStateDescriptors | 201 | 201: Error in installation. Please Check installation or call for support | decompiled.js@17875351 | high
DeviceStateDescriptors | 202 | 202: Input Voltage too lownot able to charge. Please call your installer | decompiled.js@17875458 | high
DeviceStateDescriptors | 206 | 206: Temporary set to unavailable. Contact CPO or try again later | decompiled.js@17875564 | high
DeviceStateDescriptors | 208 | 208 | decompiled.js@17875663 | high
DeviceStateDescriptors | 209 | 209 | decompiled.js@17875700 | high
DeviceStateDescriptors | 210 | 210 | decompiled.js@17875737 | high
DeviceStateDescriptors | 211 | 211: Not able to lock cable. Please call for support | decompiled.js@17875774 | high
DeviceStateDescriptors | 212 | 212: Error in installation. Please Check installation or call for support | decompiled.js@17875860 | high
DeviceStateDescriptors | 301 | 301: One moment please... Your charging session will resume shortly. | decompiled.js@17875967 | high
DeviceStateDescriptors | 302 | 302: One moment please... Your charging session will resume shortly. | decompiled.js@17876069 | high
DeviceStateDescriptors | 303 | 303: Charging not started yet. To continue please reconnect cable. | decompiled.js@17876171 | high
DeviceStateDescriptors | 304 | 304: Charging not started. yet to continue please reconnect cable. | decompiled.js@17876271 | high
DeviceStateDescriptors | 401 | 401: Inside temperature high. Charging will resume shortly. | decompiled.js@17876371 | high
DeviceStateDescriptors | 402 | 402: Inside temperature low. Charging will resume shortly. | decompiled.js@17876464 | high
DeviceStateDescriptors | 403 | 403: Charging not started yet. To continue please reconnect cable. | decompiled.js@17876556 | high
DeviceStateDescriptors | 404 | 404: Not able to lock cable. Please reconnect cable." | decompiled.js@17876656 | high
DeviceStateDescriptors | 405 | 405: Cable not supported. Please try connecting your cable again | decompiled.js@17876743 | high
DeviceStateDescriptors | 406 | 406: No communication with vehicle. Please check your charging cable | decompiled.js@17876841 | high
DeviceStateDescriptors | 407 | 407 | decompiled.js@17876943 | high

#### DirectStart
DirectStart | explanation | A default charging profile is setup on your charging station. Therefore, charging is suspended during peak hours.{newLine}If you want to override this behaviour for the current or next peak hours, press the button "{activate}" below. | decompiled.js@17876980 | high
DirectStart | notSupported | Your charging station does not support Direct Start. | decompiled.js@17877618 | high
DirectStart | explanationPrice | Please note that charging rates can be significantly higher during peak hours. | decompiled.js@17877244 | high
DirectStart | noDefaultProfile | You charging station has no default charging profile, so you don't need to override it | decompiled.js@17877496 | high
DirectStart | explantionEndOverride | This override ends when the charging session is stopped and when shifting back to non peak hours. | decompiled.js@17877358 | high
DirectStart | randomDelayDescription | To prevent peaks on the electricity grid when peak hours start or stop, charging stations must apply a random delay, so they don't start or stop charging all at once. Here you can configure the maximum duration of this random delay. | decompiled.js@17877702 | high

#### LedStateDescriptors
LedStateDescriptors | 01 | Led Off | decompiled.js@17943952 | high
LedStateDescriptors | 03 | Check Main Switch | decompiled.js@17943989 | high
LedStateDescriptors | 05 | Authorizing | decompiled.js@17944036 | high
LedStateDescriptors | 06 | Authorized | decompiled.js@17944077 | high
LedStateDescriptors | 10 | Waiting on vehicle | decompiled.js@17944117 | high
LedStateDescriptors | 14 | HighFrequency Switching | decompiled.js@17944165 | high
LedStateDescriptors | 15 | Vehicle Disconnected | decompiled.js@17944218 | high
LedStateDescriptors | 18 | Protective Earth error | decompiled.js@17944268 | high
LedStateDescriptors | 19 | Powerline Fault error | decompiled.js@17944320 | high
LedStateDescriptors | 20 | Relays error | decompiled.js@17944371 | high
LedStateDescriptors | 21 | Charging error | decompiled.js@17944413 | high
LedStateDescriptors | 22 | Power failure | decompiled.js@17944457 | high
LedStateDescriptors | 23 | Temperature error | decompiled.js@17944500 | high
LedStateDescriptors | 24 | Illegal CP Value | decompiled.js@17944547 | high
LedStateDescriptors | 25 | Illegal PP Value | decompiled.js@17944593 | high
LedStateDescriptors | 26 | Tamper Detection | decompiled.js@17944639 | high
LedStateDescriptors | 27 | Too many Restarts | decompiled.js@17944685 | high
LedStateDescriptors | 29 | Not Authorized Error | decompiled.js@17944732 | high
LedStateDescriptors | 30 | Cable Not Supported | decompiled.js@17944782 | high
LedStateDescriptors | 32 | Cable Disconnected | decompiled.js@17944831 | high
LedStateDescriptors | 35 | Limited by Smart Charging | decompiled.js@17944879 | high
LedStateDescriptors | 36 | Stopped by Smart Charging | decompiled.js@17944934 | high
LedStateDescriptors | 37 | Tag Mode active | decompiled.js@17944989 | high
LedStateDescriptors | 38 | Card Added | decompiled.js@17945034 | high
LedStateDescriptors | 39 | Card Removed | decompiled.js@17945074 | high

#### MainStateDescriptors
MainStateDescriptors | -1 | Illegal | decompiled.js@17948444 | high
MainStateDescriptors | 04 | Authorization TimeOut | decompiled.js@17948482 | high
MainStateDescriptors | 06 | Button Pushed | decompiled.js@17948534 | high
MainStateDescriptors | 07 | Card Presented | decompiled.js@17948578 | high
MainStateDescriptors | 09 | Wait on Vehicle | decompiled.js@17948623 | high
MainStateDescriptors | 11 | Charging Stopped | decompiled.js@17948669 | high
MainStateDescriptors | 12 | Waiting for power | decompiled.js@17948716 | high
MainStateDescriptors | 13 | Start Charging | decompiled.js@17948764 | high
MainStateDescriptors | 16 | Vehicle not Connected | decompiled.js@17948809 | high
MainStateDescriptors | 18 | Restart Charging | decompiled.js@17948861 | high
MainStateDescriptors | 19 | Disconnect Cable | decompiled.js@17948908 | high
MainStateDescriptors | 20 | Present Card | decompiled.js@17948955 | high
MainStateDescriptors | 21 | Restart after Outage | decompiled.js@17948998 | high
MainStateDescriptors | 24 | Cable not Supported | decompiled.js@17949049 | high
MainStateDescriptors | 25 | Illegal Charge mode | decompiled.js@17949099 | high
MainStateDescriptors | 26 | Too many retries | decompiled.js@17949149 | high
MainStateDescriptors | 29 | HighFrequent Switching | decompiled.js@17949196 | high
MainStateDescriptors | 31 | Protective Earth | decompiled.js@17949249 | high
MainStateDescriptors | 32 | Relays Errors | decompiled.js@17949296 | high
MainStateDescriptors | 33 | Power Failure | decompiled.js@17949340 | high
MainStateDescriptors | 34 | Internal Voltage Error | decompiled.js@17949384 | high
MainStateDescriptors | 35 | Power Meter Error | decompiled.js@17949437 | high
MainStateDescriptors | 36 | Temperature Error | decompiled.js@17949485 | high
MainStateDescriptors | 40 | RCD Error | decompiled.js@17949533 | high
MainStateDescriptors | 41 | Charging Suspended | decompiled.js@17949573 | high
MainStateDescriptors | 43 | Changing Phase | decompiled.js@17949622 | high
MainStateDescriptors | 44 | Wait for Start Value | decompiled.js@17949667 | high
MainStateDescriptors | 45 | Wait for Stop Value | decompiled.js@17949718 | high
MainStateDescriptors | 46 | Socket Motor Error | decompiled.js@17949768 | high
MainStateDescriptors | 47 | Schuko cable connected | decompiled.js@17949817 | high
MainStateDescriptors | 48 | Schuko Autorization timeout | decompiled.js@17949870 | high
MainStateDescriptors | 49 | Schuko Charging | decompiled.js@17949928 | high
MainStateDescriptors | 50 | Disconnect Schuko Cable | decompiled.js@17949974 | high
MainStateDescriptors | 51 | Schuko Charging disconnected | decompiled.js@17950028 | high
MainStateDescriptors | 52 | Schuko Power Failure | decompiled.js@17950087 | high
MainStateDescriptors | 53 | Invalid Card | decompiled.js@17950138 | high

#### ModbusTCPIPConnectionStateDescriptors
ModbusTCPIPConnectionStateDescriptors | 0 | Not in use (Idle) | decompiled.js@17953566 | high
ModbusTCPIPConnectionStateDescriptors | 1 | Connecting (initializing) | decompiled.js@17953630 | high
ModbusTCPIPConnectionStateDescriptors | 2 | Connected (Normal) | decompiled.js@17953702 | high
ModbusTCPIPConnectionStateDescriptors | 3 | Connection Interrupted (Warning) | decompiled.js@17953767 | high
ModbusTCPIPConnectionStateDescriptors | 4 | No Connection | decompiled.js@17953846 | high

#### Mode3StateDescriptors
Mode3StateDescriptors | 160 | Plugged in, no vehicle present | decompiled.js@17953906 | high
Mode3StateDescriptors | 177 | Vehicle connected, ready to start | decompiled.js@17953969 | high
Mode3StateDescriptors | 178 | Vehicle connected, starting… | decompiled.js@17954035 | high
Mode3StateDescriptors | 193 | Charging stopped by charge point | decompiled.js@17954096 | high
Mode3StateDescriptors | 194 | Charging… | decompiled.js@17954161 | high
Mode3StateDescriptors | 209 | Charging paused (ventilating) | decompiled.js@17954203 | high
Mode3StateDescriptors | 210 | Charging, vehicle ventilating | decompiled.js@17954265 | high
Mode3StateDescriptors | 224 | Charge point available | decompiled.js@17954327 | high
Mode3StateDescriptors | 240 | Charge point unavailable | decompiled.js@17954382 | high

#### OCPPBootNotificationStateDescriptors
OCPPBootNotificationStateDescriptors | 0 | Not Sent | decompiled.js@17959473 | high
OCPPBootNotificationStateDescriptors | 1 | Awaiting Reply | decompiled.js@17959527 | high
OCPPBootNotificationStateDescriptors | 2 | Rejected | decompiled.js@17959587 | high
OCPPBootNotificationStateDescriptors | 3 | Accepted | decompiled.js@17959641 | high
OCPPBootNotificationStateDescriptors | 4 | Pending | decompiled.js@17959695 | high

#### PowerStateDescriptors
PowerStateDescriptors | 0 | Normal Operation | decompiled.js@17963244 | high
PowerStateDescriptors | 1 | Emergency On, Bypass Off | decompiled.js@17963291 | high
PowerStateDescriptors | 2 | Emergency On, Bypass On | decompiled.js@17963346 | high

#### RegisterDataTypeDescriptors
RegisterDataTypeDescriptors | 0 | SIGNED16 | decompiled.js@17964708 | high
RegisterDataTypeDescriptors | 1 | UNSIGNED16 | decompiled.js@17964753 | high
RegisterDataTypeDescriptors | 2 | SIGNED32 | decompiled.js@17964800 | high
RegisterDataTypeDescriptors | 3 | UNSIGNED32 | decompiled.js@17964845 | high
RegisterDataTypeDescriptors | 4 | SIGNED64 | decompiled.js@17964892 | high
RegisterDataTypeDescriptors | 5 | UNSIGNED64 | decompiled.js@17964937 | high
RegisterDataTypeDescriptors | 6 | FLOAT32 | decompiled.js@17964984 | high
RegisterDataTypeDescriptors | 7 | FLOAT64 | decompiled.js@17965028 | high

#### SocketStatusDescriptors
SocketStatusDescriptors | 0 | Operative | decompiled.js@17973807 | high
SocketStatusDescriptors | 1 | In-Operative | decompiled.js@17973849 | high
SocketStatusDescriptors | Operative | Operative | decompiled.js@17973949 | high
SocketStatusDescriptors | InOperative | In-Operative | decompiled.js@17973894 | high

#### chargingStationModbusFunctionCodeDescriptors
chargingStationModbusFunctionCodeDescriptors | inputRegisters | Input registers | decompiled.js@17860553 | high
chargingStationModbusFunctionCodeDescriptors | holdingRegisters | Holding registers | decompiled.js@17860467 | high

#### chargingStationOnlineActionTypeDescriptors
chargingStationOnlineActionTypeDescriptors | 0 | Pre Authorize with local lists | decompiled.js@17862188 | high
chargingStationOnlineActionTypeDescriptors | 1 | Wait for authorization by BackOffice | decompiled.js@17862270 | high

#### chargingStationParityDescriptors
chargingStationParityDescriptors | odd | Odd | decompiled.js@17862407 | high
chargingStationParityDescriptors | even | Even | decompiled.js@17862358 | high

#### chargingStationProtocolDescriptors
chargingStationProtocolDescriptors | 1.5 | OCPP 1.5 | decompiled.js@17862754 | high
chargingStationProtocolDescriptors | 1.6 | OCPP 1.6 | decompiled.js@17862808 | high
chargingStationProtocolDescriptors | 2.0.1 | OCPP 2.0.1 | decompiled.js@17862862 | high

#### chargingStationWordOrderDescriptors
chargingStationWordOrderDescriptors | highToLow | High to Low | decompiled.js@17865235 | high
chargingStationWordOrderDescriptors | lowToHigh | Low to High | decompiled.js@17865299 | high

#### errorDescriptors
errorDescriptors | ENTITY_ALREADY_EXISTS | This is not available, it might already be in use. | decompiled.js@17883514 | high
errorDescriptors | INTERNAL_SERVER_ERROR | Something went wrong, please try again. | decompiled.js@17883610 | high

### Hardcoded enum tables (code modules, decompiled.js ~30376000–30430000)

CSLanguageValue (string values, used by 205D_0 display language): en_GB, nl_NL, de_DE, fr_FR, it_IT, nn_NO, de_LU, pt_PT, es_ES, sv_SE, fi_FI, pl_PL, da_DK, ro_RO, cz_CZ, cs_CZ, hu_HU, is_IS, lv_LV, sk_SK, si_SL, ca_ES, hr_HR | decompiled.js@30378852 | high

## Unit strings

Units are embedded in the display names (no separate unit field): '(A)' = amps (2062_0, 2067_0, 2068_0, 2068_1, 2068_2, 206A_0), '(s)' = seconds (206B_2), '(W)' = watts (206B_3), '(kWh)' on energy meter regs, '(ms)' where noted, '(EUR)'-style currency on 3262_1 'EUR'.

## Read/write hints

* Properties with an entry in the rules module (211, listed above) are WRITABLE via the app's commissioning forms (defaultValue present).
* Properties fetched but never in rules (e.g. 2056_0 Number of bootups, 2057_0 Boot Reason, 2060_0 System uptime, meter regs 21xx) are read-only telemetry.
* The app groups ids into named fetch batches; e.g. batch 'ChargingStation' = ['100A_00','2050_00','2051_00','2053_00','2054_00','2059_00','205C_01','205C_02',...] | decompiled.js@28656108

## API usage

* Endpoint `/api/cmdn_url` string present in bundle (custom Alfen API path) | bundle strings.
* Property values are addressed by the same `id` strings; app normalizes to zero-padded `PPPP_SS`.
