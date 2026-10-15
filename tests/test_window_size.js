const { test } = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { defaultWindowSize, fitBounds, installDisplaySizing, referenceZoom } = require('../lib/window-size')

test('the default stays moderate on a 1080p desktop and larger monitors', () => {
  const size = defaultWindowSize({ width: 1920, height: 1040 })
  assert.equal(size.width, 1520)
  assert.equal(size.height, 976)
  assert.equal(defaultWindowSize({width:3840,height:2120}).height,980)
})

test('smaller desktops retain margins and allow the window below the usual minimum', () => {
  for (const workArea of [{ width: 1366, height: 728 }, { width: 1280, height: 680 }, { width: 1024, height: 728 }]) {
    const size = defaultWindowSize(workArea)
    assert(workArea.width - size.width >= 40)
    assert(workArea.height - size.height >= 40)
    assert(size.minWidth <= size.width && size.minHeight <= size.height)
  }
})

test('high Windows scaling matches the approved physical window and typography', () => {
  // The current 187.5% display reports this logical work area to Electron.
  const area={width:1195,height:709},dpi=1.875,size=defaultWindowSize(area,dpi),zoom=referenceZoom(dpi,area)
  assert.equal(size.width,810)
  assert.equal(size.height,522)
  assert(size.width*dpi<=1520&&size.height*dpi<=980)
  assert(Math.abs(size.width/zoom-1280)<2)
  assert.equal(16*zoom*dpi,19)
})

test('the mainstream 1080p, 2240x1400 and 4K desktops keep the approved proportions', () => {
  for(const [width,height,dpi] of [[1920,1080,1],[2240,1400,1.5],[3840,2160,1],[3840,2160,1.5],[3840,2160,2]]){
    const area={width:width/dpi,height:(height-48*dpi)/dpi},size=defaultWindowSize(area,dpi),zoom=referenceZoom(dpi,area)
    assert(size.width*dpi<=1520&&size.height*dpi<=980)
    assert(width-size.width*dpi>=64&&height-size.height*dpi>=64)
    assert(Math.abs(size.width/zoom-1280)<2)
    assert(Math.abs(16*zoom*dpi-19)<.001)
  }
})

test('100 to 250 percent Windows DPI keeps the same screen-pixel reference', () => {
  for(const dpi of [1,1.25,1.5,1.875,2,2.5]){
    const area={width:1920/dpi,height:1040/dpi},size=defaultWindowSize(area,dpi),zoom=referenceZoom(dpi,area)
    assert(Math.abs(size.width*dpi-1520)<=dpi)
    assert(Math.abs(size.height*dpi-976)<=dpi)
    assert(Math.abs(16*zoom*dpi-19)<.001)
    assert(size.minWidth<=size.width&&size.minHeight<=size.height)
  }
})

test('small screens keep useful CSS space without making normal text smaller than 16 screen pixels', () => {
  for(const area of [{width:1024,height:728},{width:1280,height:680},{width:1366,height:728}]){
    const size=defaultWindowSize(area),zoom=referenceZoom(1,area)
    assert(size.width/zoom>=959&&size.height/zoom>=539)
    assert(16*zoom>=16)
  }
})

test('scaled work areas and negative monitor coordinates keep windows reachable', () => {
  for (const area of [{x:-1536,y:0,width:1536,height:824}, {x:1920,y:-720,width:1024,height:720}, {x:0,y:0,width:768,height:520}]) {
    const bounds = fitBounds(area, {x:-2000,y:1000,width:1600,height:1000})
    assert(bounds.x>=area.x && bounds.y>=area.y)
    assert(bounds.x+bounds.width<=area.x+area.width && bounds.y+bounds.height<=area.y+area.height)
  }
})

test('moving monitors adapts once, preserves manual size, handles resolution changes and removes listeners', async () => {
  const screen = new EventEmitter(), window = new EventEmitter()
  const contents=new EventEmitter();let zoom=1;Object.assign(contents,{getZoomFactor:()=>zoom,setZoomFactor:v=>{zoom=v}});window.webContents=contents
  let display={id:1,workArea:{x:0,y:0,width:1920,height:1040}}, bounds={x:100,y:50,width:1200,height:800}, maximized=false, writes=0
  screen.getDisplayMatching=()=>display
  Object.assign(window,{getBounds:()=>bounds,setBounds:v=>{bounds=v;writes++},setMinimumSize:()=>{},isDestroyed:()=>false,isMaximized:()=>maximized,isMinimized:()=>false,isFullScreen:()=>false})
  const settle=()=>new Promise(resolve=>setTimeout(resolve,230))
  installDisplaySizing(window,screen,display)
  window.emit('move');await settle();assert.equal(writes,0)
  display={id:2,workArea:{x:-1024,y:0,width:1024,height:720}}
  window.emit('move');await settle();assert(bounds.x<0);assert(bounds.width<1024 && bounds.height<720)
  bounds={...bounds,width:800,height:600};window.emit('move');await settle();assert.equal(bounds.width,800)
  maximized=true;display.workArea.height=600;screen.emit('display-metrics-changed');await settle();assert.equal(bounds.height,600)
  maximized=false;window.emit('unmaximize');await settle();assert(bounds.height<600)
  display={id:2,scaleFactor:1.875,workArea:{x:0,y:0,width:1195,height:709}}
  screen.emit('display-metrics-changed');await settle();assert.equal(bounds.width,810);assert.equal(bounds.height,522);assert.equal(zoom,referenceZoom(1.875,display.workArea))
  window.emit('closed');assert.equal(screen.listenerCount('display-metrics-changed'),0)
  assert.equal(screen.listenerCount('display-removed'),0)
})
