ALMS_RoadAmerica
{
  AI Vehicle Filter = 

  RacePitKPH = 60
  NormalPitKPH = 60
  FormationSpeedKPH = 80
  TestDayDay = Thursday
  TestDayStart = 17:30
  Practice1Day = Friday
  Practice1Start = 10:35
  Practice1Duration = 60:00
  Practice2Day = Friday
  Practice2Start = 20:15
  Practice2Duration = 60:00
  Qualify1Day = Saturday
  Qualify1Start = 15:25
  Qualify1Duration = 60:00
  Qualify2Day = Saturday
  Qualify2Start = 16:30
  Qualify2Duration = 60:00
  WarmupDay = Sunday
  WarmupStart = 09:00
  WarmupDuration = 15:00
  RaceDay = Sunday
  RaceStart = 12:30 
  RaceLaps = 135
  RaceTime = 240
  RaceTimeScaled = 240

  Attrition = 15

  TrackName = ALMS Road America
  GrandPrixName = ALMS Road America
  EventName = ALMS Road America
  VenueName = ALMS Road America 2008
  Location = Elkhart Lake, Wisconsin, USA
  Length = 4.05 miles / 6.515 km
  TrackType = Permanent Road Course

  RoadDryGrip = 1.02
  AIDryGrip = 1.02
  RoadWetGrip = 0.75
  AIWetGrip = 0.75
  PlayerTireWear = 1.1
  FrontTireHeatMult = 1.05
  RearTireHeatMult = 1.05

  SettingsFolder = ALMS_RoadAmerica
  SettingsCopy = ALMS_RoadAmerica.svm
  SettingsAI = ALMS_RoadAmerica.svm
  Qualify Laptime = 113.000
  Race Laptime = 115.000

  // Scene Lighting

  // Locality
  Region = North
  Average rain = 0.05
  RainLightScale = 0.85
  RainFogScale = 0.95
  RainFogColourScale = 0.15
  RainCloudScale = 1.0

  ShadowMinSunAngle=18.0

  SunriseAmbientColour = (100,100,75)
  SunriseDirectionalColour = (20,10,5)
  SunriseFogColour = (30,35,55)
  SunriseFogIn = 0.0
  SunriseFogOut = 1950.0
  RainSunriseAmbientColour = (85,85,85)
  RainSunriseDirectionalColour = (45,45,45)
  RainSunriseFogColour = (43,53,55)
  RainSunriseFogIn = -50.0
  RainSunriseFogOut = 1500.0

  DayAmbientColour =(87,84,75)
  DayDirectionalColour = (255,247,225)
  DayFogColour = (133,158,198)
  DayFogIn = 20.0
  DayFogOut = 2450.0
  RainDayAmbientColour = (105,105,105)
  RainDayDirectionalColour = (45,45,45)
  RainDayFogColour = (79,80,80)
  RainDayFogIn = -50.0
  RainDayFogOut = 1500.0

  SunsetAmbientColour = (126,110,110)
  SunsetDirectionalColour = (58,38,38)
  SunsetFogColour = (90,93,115)
  SunsetFogIn = 100.0
  SunsetFogOut = 1800.0
  RainSunsetAmbientColour = (72,70,70)
  RainSunsetDirectionalColour = (35,32,32)
  RainSunsetFogColour = (37,41,35) 
  RainSunsetFogIn = -50.0
  RainSunsetFogOut = 1500.0

  NightAmbientColour = (15,17,10)
  NightDirectionalColour = (9,2,4)
  NightFogColour = (4,7,10)
  NightFogIn = 220.0
  NightFogOut = 1250.0
  RainNightAmbientColour = (25,25,25)
  RainNightDirectionalColour = (15,15,15)
  RainNightFogColour = (23,25,24)
  RainNighttFogIn = -50.0
  RainNightFogOut = 1500.0

  // Sun position
  // Latitude affects day/night length, used with date.
  // Latitude also controls the sun/moon vector across the sky
  // NorthDir controls where sun rises/sets
  // RaceDate affects length of day/night, used with latitude

  Latitude = 43.8 // in degrees, -90 ... +90 (def. 0)
  NorthDir = 90 // in degrees (def. 245)
  RaceDate = August 20 // (def. July 1)

  Max Vehicles = 102

// Pitstop locations in order from front to back ... if these need to be
// reversed on an individual track, set "ReversePitOrder=1" in the
// track-specific GDB file.

 PitOrder
 {
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
  PitGroup=
 }

// Number of vehicles sharing each pitstall.  The number of entries
// here must match the number of entries in the PitOrder above.

 NumberSharingPit
 {
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
  Vehicles=3 // 
 } 
} 

