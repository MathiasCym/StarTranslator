const { test } = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { defaultWindowSize, fitBounds, installDisplaySizing } = require('../lib/window-size')

test('the default stays moderate on a 1080p desktop and larger monitors', () => {
  const size = defaultWindowSize({ width: 1920, height: 1040 })
  assert.equal(size.width, 1280)
  assert.equal(size.height, 820)
  assert.deepEqual(defaultWindowSize({width:3840,height:2120}),size)
})

test('smaller desktops retain margins and allow the window below the usual minimum', () => {
  for (const workArea of [{ width: 1366, height: 728 }, { width: 1280, height: 680 }, { width: 1024, height: 728 }]) {
    const size = defaultWindowSize(workArea)
    assert(workArea.width - size.width >= 40)
    assert(workArea.height - size.height >= 40)
    assert(size.minWidth <= size.width && size.minHeight <= size.height)
  }
})

test('high Windows scaling leaves real desktop space without shrinking text through zoom', () => {
  // The current 187.5% display reports this logical work area to Electron.
  const size=defaultWindowSize({width:1195,height:709})
  assert.equal(size.width,1028)
  assert.equal(size.height,610)
  assert(size.width/1195<.87&&size.height/709<.87)
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
  window.emit('closed');assert.equal(screen.listenerCount('display-metrics-changed'),0)
  assert.equal(screen.listenerCount('display-removed'),0)
})
