import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('atlasDesktop', {
  getConnection: profile => ipcRenderer.invoke('atlas:connection', profile),
  revalidateConnection: () => ipcRenderer.invoke('atlas:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('atlas:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('atlas:gateway:ws-url', profile),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('atlas:window:openSession', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('atlas:window:openInstance'),
  claimAmbientCue: key => ipcRenderer.invoke('atlas:ambient:claim', key),
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('atlas:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('atlas:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('atlas:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('atlas:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('atlas:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('atlas:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('atlas:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('atlas:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('atlas:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('atlas:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('atlas:pet-overlay:control', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('atlas:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('atlas:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('atlas:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('atlas:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('atlas:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('atlas:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('atlas:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('atlas:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('atlas:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('atlas:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('atlas:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('atlas:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('atlas:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('atlas:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('atlas:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('atlas:connection-config:test', payload),
  sshConfigHosts: () => ipcRenderer.invoke('atlas:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('atlas:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('atlas:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('atlas:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('atlas:connection-config:oauth-logout', remoteUrl),
  // Atlas Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('atlas:cloud:status'),
    login: () => ipcRenderer.invoke('atlas:cloud:login'),
    logout: () => ipcRenderer.invoke('atlas:cloud:logout'),
    discover: org => ipcRenderer.invoke('atlas:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('atlas:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    get: () => ipcRenderer.invoke('atlas:profile:get'),
    set: name => ipcRenderer.invoke('atlas:profile:set', name)
  },
  api: request => ipcRenderer.invoke('atlas:api', request),
  notify: payload => ipcRenderer.invoke('atlas:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('atlas:requestMicrophoneAccess'),
  readFileDataUrl: filePath => ipcRenderer.invoke('atlas:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('atlas:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('atlas:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('atlas:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('atlas:readFileText', filePath),
  selectPaths: options => ipcRenderer.invoke('atlas:selectPaths', options),
  writeClipboard: text => ipcRenderer.invoke('atlas:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('atlas:readClipboard'),
  saveImageFromUrl: url => ipcRenderer.invoke('atlas:saveImageFromUrl', url),
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('atlas:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('atlas:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('atlas:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('atlas:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('atlas:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('atlas:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('atlas:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('atlas:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('atlas:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('atlas:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('atlas:keep-awake', on),
  setPreviewShortcutActive: active => ipcRenderer.send('atlas:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('atlas:openExternal', url),
  // Restart into a version the updater has already put on disk. Takes the
  // Windows installer path when there is one, because a running .exe cannot be
  // replaced and the handover is to that installer, not to ourselves.
  restartApp: installerPath => ipcRenderer.invoke('atlas:app:restart', installerPath ?? null),
  openPreviewInBrowser: url => ipcRenderer.invoke('atlas:openPreviewInBrowser', url),
  fetchLinkTitle: url => ipcRenderer.invoke('atlas:fetchLinkTitle', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('atlas:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('atlas:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('atlas:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('atlas:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('atlas:zoom:get'),
    setPercent: percent => ipcRenderer.send('atlas:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('atlas:zoom:changed', listener)

      return () => ipcRenderer.removeListener('atlas:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('atlas:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('atlas:logs:recent'),
  readDir: dirPath => ipcRenderer.invoke('atlas:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('atlas:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('atlas:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('atlas:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('atlas:fs:desktopPluginsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('atlas:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('atlas:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('atlas:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('atlas:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('atlas:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('atlas:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('atlas:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('atlas:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('atlas:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('atlas:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('atlas:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('atlas:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('atlas:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('atlas:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('atlas:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('atlas:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('atlas:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('atlas:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('atlas:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('atlas:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('atlas:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('atlas:git:review:shipInfo', repoPath),
      createPr: repoPath => ipcRenderer.invoke('atlas:git:review:createPr', repoPath)
    }
  },
  terminal: {
    cwd: id => ipcRenderer.invoke('atlas:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('atlas:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('atlas:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('atlas:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('atlas:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `atlas:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `atlas:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('atlas:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('atlas:close-preview-requested', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('atlas:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('atlas:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('atlas:open-updates', listener)

    return () => ipcRenderer.removeListener('atlas:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:deep-link', listener)

    return () => ipcRenderer.removeListener('atlas:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('atlas:deep-link-ready'),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:window-state-changed', listener)

    return () => ipcRenderer.removeListener('atlas:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('atlas:focus-session', listener)

    return () => ipcRenderer.removeListener('atlas:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:notification-action', listener)

    return () => ipcRenderer.removeListener('atlas:notification-action', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('atlas:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:backend-exit', listener)

    return () => ipcRenderer.removeListener('atlas:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('atlas:connection:applied', listener)

    return () => ipcRenderer.removeListener('atlas:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('atlas:power-resume', listener)

    return () => ipcRenderer.removeListener('atlas:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('atlas:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('atlas:power-battery', listener)

    return () => ipcRenderer.removeListener('atlas:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:boot-progress', listener)

    return () => ipcRenderer.removeListener('atlas:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('atlas:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('atlas:bootstrap:continue-local'),
  resetBootstrap: () => ipcRenderer.invoke('atlas:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('atlas:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('atlas:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('atlas:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('atlas:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('atlas:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('atlas:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('atlas:uninstall:summary'),
    run: mode => ipcRenderer.invoke('atlas:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('atlas:updates:check'),
    apply: opts => ipcRenderer.invoke('atlas:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('atlas:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('atlas:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('atlas:updates:progress', listener)

      return () => ipcRenderer.removeListener('atlas:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('atlas:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('atlas:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('atlas:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('atlas:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('atlas:found-in-page', listener)

    return () => ipcRenderer.removeListener('atlas:found-in-page', listener)
  }
})
