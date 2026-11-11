import AppKit
import Foundation
import SwiftUI
import Translation

#if canImport(FoundationModels)
import FoundationModels
#endif

struct MenuAction: Identifiable {
    let id: String
    let title: String
    let symbol: String
    let key: String
}

struct LanguageChoice: Identifiable {
    let id: String
    let title: String
}

private let actions: [MenuAction] = [
    MenuAction(id: "speak", title: "Speak", symbol: "speaker.wave.2.fill", key: "1"),
    MenuAction(id: "proofread", title: "Proofread", symbol: "checkmark.circle", key: "2"),
    MenuAction(id: "rewrite", title: "Rewrite", symbol: "pencil.line", key: "3"),
    MenuAction(id: "translate", title: "Translate", symbol: "translate", key: "4"),
]

private let languages: [LanguageChoice] = [
    LanguageChoice(id: "en", title: "English"),
    LanguageChoice(id: "vi", title: "Vietnamese"),
    LanguageChoice(id: "ja", title: "Japanese"),
    LanguageChoice(id: "ko", title: "Korean"),
    LanguageChoice(id: "zh-Hans", title: "Chinese"),
    LanguageChoice(id: "fr", title: "French"),
    LanguageChoice(id: "de", title: "German"),
    LanguageChoice(id: "es", title: "Spanish"),
]

private func shortLanguage(_ code: String) -> String {
    switch code {
    case "en": return "EN"
    case "vi": return "VI"
    case "ja": return "JA"
    case "ko": return "KO"
    case "zh-Hans": return "ZH"
    case "fr": return "FR"
    case "de": return "DE"
    case "es": return "ES"
    default: return code
    }
}

final class MenuModel: ObservableObject {
    @Published var sourceText = ""
    @Published var translateLanguage: String?
    @Published var opened = false
    @Published var showLanguages = false
    @Published var center = CGPoint.zero
    @Published var screenFrame = CGRect.zero
    @Published var busyTitle: String?
    @Published var previewTitle: String?
    @Published var previewText: String?
    @Published var errorText: String?
    @Published var translationConfig: TranslationSession.Configuration?
    @Published var languagesOpened = false
    @Published var hoverID: String?
    @Published var selectionEditable = false
    var onDismiss: () -> Void = {}
    private var job = 0
    private var anchor = CGPoint.zero

    func present(text: String, language: String?, editable: Bool) {
        job += 1
        sourceText = text
        translateLanguage = language
        selectionEditable = editable
        showLanguages = false
        languagesOpened = false
        busyTitle = nil
        previewTitle = nil
        previewText = nil
        errorText = nil
        anchor = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(anchor) } ?? NSScreen.main
        screenFrame = screen?.frame ?? .zero
        hoverID = nil
        center = shifted(anchor, radius: WheelLayout.outer, screen: screen)
        opened = false
        DispatchQueue.main.async {
            self.opened = true
        }
    }

    func dismiss() {
        onDismiss()
    }

    func press(_ key: String) {
        guard busyTitle == nil, previewText == nil, errorText == nil else { return }
        if showLanguages {
            let index = (Int(key) ?? 0) - 1
            guard languages.indices.contains(index) else { return }
            chooseLanguage(languages[index].id)
            return
        }
        switch key {
        case "1": run("speak")
        case "2": run("proofread")
        case "3": run("rewrite")
        case "4": run("translate")
        default: break
        }
    }

    func run(_ id: String) {
        guard busyTitle == nil, previewText == nil, errorText == nil else { return }
        switch id {
        case "speak":
            emit(["event": "speak"])
            dismiss()
        case "proofread":
            rewrite(proof: true)
        case "rewrite":
            rewrite(proof: false)
        case "translate":
            if let code = translateLanguage, !code.isEmpty {
                startTranslation(code)
            } else {
                hoverID = nil
                showLanguages = true
                languagesOpened = false
                DispatchQueue.main.async {
                    self.languagesOpened = true
                }
            }
        default:
            break
        }
    }

    func chooseLanguage(_ code: String) {
        translateLanguage = code
        showLanguages = false
        emit(["event": "language", "code": code])
        startTranslation(code)
    }

    func replace() {
        guard let previewText else { return }
        emit(["event": "replace", "text": previewText])
        dismiss()
    }

    func copy() {
        guard let previewText else { return }
        emit(["event": "copy", "text": previewText])
        dismiss()
    }

    func fail(_ message: String) {
        busyTitle = nil
        previewText = nil
        previewTitle = nil
        errorText = message
    }

    private func startTranslation(_ code: String) {
        job += 1
        busyTitle = "Translating…"
        errorText = nil
        previewText = nil
        previewTitle = nil
        let target = Locale.Language(identifier: code)
        if var config = translationConfig, config.target == target {
            config.invalidate()
            translationConfig = config
        } else {
            translationConfig = TranslationSession.Configuration(source: nil, target: target)
        }
    }

    func applyTranslation(_ text: String, token: Int) {
        guard token == job else { return }
        busyTitle = nil
        errorText = nil
        previewTitle = "Translate"
        previewText = text
    }

    func failTranslation(_ message: String, token: Int) {
        guard token == job else { return }
        fail(message)
    }

    var translationToken: Int { job }

    private func rewrite(proof: Bool) {
        job += 1
        let token = job
        let title = proof ? "Proofread" : "Rewrite"
        busyTitle = proof ? "Proofreading…" : "Rewriting…"
        errorText = nil
        previewText = nil
        let source = sourceText
        Task {
            do {
                let text = try await appleIntelligence(source, proof: proof)
                await MainActor.run {
                    guard token == self.job else { return }
                    self.busyTitle = nil
                    self.previewTitle = title
                    self.previewText = text
                }
            } catch {
                await MainActor.run {
                    guard token == self.job else { return }
                    self.fail(error.localizedDescription)
                }
            }
        }
    }

    func wheelEntries() -> [WheelEntry] {
        if showLanguages {
            return languages.map {
                WheelEntry(id: $0.id, title: shortLanguage($0.id), symbol: "", hubTitle: $0.title)
            }
        }
        return actions.map {
            WheelEntry(id: $0.id, title: $0.title, symbol: $0.symbol, hubTitle: $0.title)
        }
    }

    func layout(in size: CGSize) -> MenuLayout {
        let wheel = CGPoint(
            x: center.x - screenFrame.minX,
            y: size.height - (center.y - screenFrame.minY)
        )
        let showing = busyTitle != nil || previewText != nil || errorText != nil
        guard showing else {
            return MenuLayout(wheel: wheel, card: nil, replace: nil, copy: nil)
        }
        let cardHeight: CGFloat = previewText != nil || errorText != nil ? 176 : 84
        let below = wheel.y + WheelLayout.outer + 14 + cardHeight / 2
        let cardY = below + cardHeight / 2 + 8 < size.height
            ? below
            : wheel.y - WheelLayout.outer - 14 - cardHeight / 2
        let cardX = min(max(wheel.x, 150), max(size.width - 150, 150))
        let card = CGRect(
            x: cardX - WheelLayout.cardWidth / 2,
            y: cardY - cardHeight / 2,
            width: WheelLayout.cardWidth,
            height: cardHeight
        )
        var replace: CGRect?
        var copy: CGRect?
        if previewText != nil {
            let row = CGRect(x: card.minX, y: card.maxY - 64, width: card.width, height: 64)
            if selectionEditable {
                replace = CGRect(x: row.minX, y: row.minY, width: row.width / 2, height: row.height)
                copy = CGRect(x: row.midX, y: row.minY, width: row.width / 2, height: row.height)
            } else {
                copy = row
            }
        }
        return MenuLayout(wheel: wheel, card: card, replace: replace, copy: copy)
    }

    func hit(_ swiftPoint: CGPoint, in size: CGSize) -> WheelHit {
        let placed = layout(in: size)
        if let replace = placed.replace, replace.contains(swiftPoint) {
            return .replace
        }
        if let copy = placed.copy, copy.contains(swiftPoint) {
            return .copy
        }
        if let card = placed.card, card.contains(swiftPoint) {
            return .card
        }
        let dx = swiftPoint.x - placed.wheel.x
        let dy = swiftPoint.y - placed.wheel.y
        let distance = hypot(dx, dy)
        if distance <= WheelLayout.hub {
            return .center
        }
        if distance > WheelLayout.outer {
            return .outside
        }
        let entries = wheelEntries()
        guard !entries.isEmpty else { return .outside }
        let sweep = 360 / CGFloat(entries.count)
        let fromTop = atan2(dy, dx) * 180 / .pi + 90
        var shifted = fromTop + sweep / 2
        shifted = shifted.truncatingRemainder(dividingBy: 360)
        if shifted < 0 {
            shifted += 360
        }
        if shifted >= 360 {
            shifted -= 360
        }
        let index = Int(shifted / sweep) % entries.count
        return .slice(entries[index].id)
    }

    private func shifted(_ point: CGPoint, radius: CGFloat, screen: NSScreen?) -> CGPoint {
        guard let screen else { return point }
        let frame = screen.visibleFrame
        let pad = radius + 8
        var center = point
        center.x = min(max(center.x, frame.minX + pad), frame.maxX - pad)
        center.y = min(max(center.y, frame.minY + pad), frame.maxY - pad)
        return center
    }
}

struct WheelEntry {
    let id: String
    let title: String
    let symbol: String
    var hubTitle: String = ""
}

struct MenuLayout {
    var wheel: CGPoint
    var card: CGRect?
    var replace: CGRect?
    var copy: CGRect?
}

enum WheelHit {
    case slice(String)
    case center
    case outside
    case card
    case replace
    case copy
}

enum WheelLayout {
    static let outer: CGFloat = 78
    static let inner: CGFloat = 40
    static let hub: CGFloat = 40
    static let cardWidth: CGFloat = 280
}

struct MenuRoot: View {
    @ObservedObject var model: MenuModel

    var body: some View {
        GeometryReader { geo in
            let placed = model.layout(in: geo.size)
            ZStack {
                ActionWheel(
                    entries: model.wheelEntries(),
                    hoverID: model.hoverID,
                    sprung: model.opened
                )
                .position(placed.wheel)
                if let card = placed.card {
                    cardView
                        .position(x: card.midX, y: card.midY)
                }
            }
        }
        .translationTask(model.translationConfig) { session in
            let token = await MainActor.run { model.translationToken }
            let source = await MainActor.run { model.sourceText }
            do {
                let response = try await session.translate(source)
                await MainActor.run {
                    model.applyTranslation(response.targetText, token: token)
                }
            } catch {
                await MainActor.run {
                    model.failTranslation(error.localizedDescription, token: token)
                }
            }
        }
    }

    @ViewBuilder
    private var cardView: some View {
        let title = model.busyTitle ?? model.previewTitle ?? (model.errorText == nil ? "" : "Could not finish")
        let message = model.previewText ?? model.errorText
        VStack(alignment: .leading, spacing: 8) {
            if message == nil {
                VStack(spacing: 10) {
                    ProgressView()
                        .controlSize(.regular)
                        .tint(.white)
                    if !title.isEmpty {
                        Text(title)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.white.opacity(0.9))
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if let message {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white)
                Text(message)
                    .font(.system(size: 13))
                    .foregroundStyle(.white.opacity(0.88))
                    .lineLimit(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer(minLength: 0)
            if model.previewText != nil {
                HStack(spacing: 8) {
                    if model.selectionEditable {
                        Text("Replace")
                            .frame(maxWidth: .infinity)
                    }
                    Text("Copy")
                        .frame(maxWidth: .infinity)
                }
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white)
                .frame(height: 32)
                .background(Color.white.opacity(0.14), in: Capsule())
            }
        }
        .padding(14)
        .frame(width: WheelLayout.cardWidth, height: model.previewText != nil || model.errorText != nil ? 176 : 84)
        .modifier(GlassChrome(shape: RoundedRectangle(cornerRadius: 22, style: .continuous)))
    }
}

struct ActionWheel: View {
    let entries: [WheelEntry]
    let hoverID: String?
    let sprung: Bool

    private var hubText: String {
        guard let hoverID, let entry = entries.first(where: { $0.id == hoverID }) else {
            return "Close"
        }
        return entry.hubTitle.isEmpty ? entry.title : entry.hubTitle
    }

    var body: some View {
        let count = max(entries.count, 1)
        let sweep = 360.0 / Double(count)
        let diameter = WheelLayout.outer * 2
        ZStack {
            Circle()
                .fill(Color.black.opacity(0.42))
                .frame(width: diameter, height: diameter)
                .modifier(LiquidGlass(shape: Circle()))
            Circle()
                .strokeBorder(
                    LinearGradient(
                        colors: [
                            Color.white.opacity(0.55),
                            Color.white.opacity(0.08),
                            Color.white.opacity(0.22),
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    lineWidth: 1
                )
                .frame(width: diameter, height: diameter)
            RingDividers(count: count)
                .stroke(Color.white.opacity(0.16), lineWidth: 0.7)
                .frame(width: diameter, height: diameter)
            ForEach(Array(entries.enumerated()), id: \.offset) { index, entry in
                let start = -90.0 - sweep / 2 + Double(index) * sweep + 1.2
                let end = start + sweep - 2.4
                let hovered = hoverID == entry.id
                if hovered {
                    SliceShape(start: .degrees(start), end: .degrees(end))
                        .fill(Color.white.opacity(0.20))
                        .frame(width: diameter, height: diameter)
                    RimArc(start: .degrees(start + 4), end: .degrees(end - 4))
                        .stroke(Color.white.opacity(0.92), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                        .frame(width: diameter, height: diameter)
                }
                entryLabel(entry, start: start, end: end, hovered: hovered)
            }
            Circle()
                .fill(Color.black.opacity(0.62))
                .frame(width: WheelLayout.hub * 2, height: WheelLayout.hub * 2)
                .modifier(LiquidGlass(shape: Circle()))
            Circle()
                .stroke(Color.white.opacity(0.16), lineWidth: 0.6)
                .frame(width: WheelLayout.hub * 2, height: WheelLayout.hub * 2)
            VStack(spacing: 4) {
                if hoverID == nil {
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .semibold))
                }
                Text(hubText)
                    .font(.system(size: hoverID == nil ? 9 : 11, weight: .semibold))
                    .lineLimit(2)
                    .minimumScaleFactor(0.7)
                    .multilineTextAlignment(.center)
            }
            .foregroundStyle(.white.opacity(hoverID == nil ? 0.72 : 0.96))
            .frame(width: WheelLayout.hub * 2 - 18)
        }
        .frame(width: diameter, height: diameter)
        .shadow(color: .black.opacity(0.35), radius: 22, y: 10)
        .scaleEffect(sprung ? 1 : 0.86)
        .animation(.spring(response: 0.42, dampingFraction: 0.78), value: sprung)
        .animation(.easeOut(duration: 0.14), value: hoverID)
        .allowsHitTesting(false)
    }

    private func entryLabel(_ entry: WheelEntry, start: Double, end: Double, hovered: Bool) -> some View {
        let mid = (start + end) / 2 * .pi / 180
        let radius = (WheelLayout.hub + WheelLayout.outer) / 2
        return Group {
            if !entry.symbol.isEmpty {
                Image(systemName: entry.symbol)
                    .font(.system(size: hovered ? 15 : 13, weight: hovered ? .semibold : .regular))
            } else {
                Text(entry.title)
                    .font(.system(size: 9, weight: hovered ? .semibold : .medium))
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
            }
        }
        .foregroundStyle(.white.opacity(hovered ? 1 : 0.62))
        .frame(width: entries.count > 4 ? 36 : 56)
        .scaleEffect(hovered ? 1.06 : 1)
        .offset(x: cos(mid) * radius, y: sin(mid) * radius)
    }
}

struct RingDividers: Shape {
    var count: Int

    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let outer = min(rect.width, rect.height) / 2
        let inner = WheelLayout.hub / WheelLayout.outer * outer
        let sweep = 360.0 / Double(max(count, 1))
        var path = Path()
        for index in 0..<max(count, 1) {
            let radians = (-90.0 - sweep / 2 + Double(index) * sweep) * .pi / 180
            path.move(to: CGPoint(x: center.x + cos(radians) * inner, y: center.y + sin(radians) * inner))
            path.addLine(to: CGPoint(x: center.x + cos(radians) * (outer - 1), y: center.y + sin(radians) * (outer - 1)))
        }
        return path
    }
}

struct RimArc: Shape {
    var start: Angle
    var end: Angle

    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let radius = min(rect.width, rect.height) / 2 - 2.5
        var path = Path()
        path.addArc(center: center, radius: radius, startAngle: start, endAngle: end, clockwise: false)
        return path
    }
}

struct SliceShape: Shape {
    var start: Angle
    var end: Angle

    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let outer = min(rect.width, rect.height) / 2
        let inner = WheelLayout.inner / WheelLayout.outer * outer
        var path = Path()
        path.addArc(center: center, radius: outer, startAngle: start, endAngle: end, clockwise: false)
        path.addArc(center: center, radius: inner, startAngle: end, endAngle: start, clockwise: true)
        path.closeSubpath()
        return path
    }
}

struct LiquidGlass<S: Shape>: ViewModifier {
    let shape: S

    func body(content: Content) -> some View {
        content.modifier(GlassChrome(shape: shape))
    }
}

struct GlassChrome<S: Shape>: ViewModifier {
    let shape: S

    func body(content: Content) -> some View {
        Group {
            if #available(macOS 26.0, *) {
                content.glassEffect(.regular.tint(Color.black.opacity(0.55)).interactive(), in: shape)
            } else {
                content.background(.ultraThinMaterial, in: shape)
            }
        }
    }
}

final class WheelHostingView: NSHostingView<MenuRoot> {
    var model: MenuModel?
    private var tracking: NSTrackingArea?

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let tracking {
            removeTrackingArea(tracking)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.activeAlways, .mouseMoved, .mouseEnteredAndExited, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        tracking = area
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        bounds.contains(point) ? self : nil
    }

    override func mouseMoved(with event: NSEvent) {
        guard let model else { return }
        if case .slice(let id) = model.hit(swiftLocation(event), in: bounds.size) {
            model.hoverID = id
        } else {
            model.hoverID = nil
        }
    }

    override func mouseExited(with event: NSEvent) {
        model?.hoverID = nil
    }

    override func mouseDown(with event: NSEvent) {
        guard let model else { return }
        switch model.hit(swiftLocation(event), in: bounds.size) {
        case .slice(let id):
            if model.showLanguages {
                model.chooseLanguage(id)
            } else {
                model.run(id)
            }
        case .replace:
            model.replace()
        case .copy:
            model.copy()
        case .card:
            break
        case .center, .outside:
            model.dismiss()
        }
    }

    override func rightMouseDown(with event: NSEvent) {
        model?.dismiss()
    }

    private func swiftLocation(_ event: NSEvent) -> CGPoint {
        let point = convert(event.locationInWindow, from: nil)
        if isFlipped {
            return point
        }
        return CGPoint(x: point.x, y: bounds.height - point.y)
    }
}

final class MenuController: NSObject, NSApplicationDelegate {
    let model = MenuModel()
    var panel: NSPanel?
    var host: WheelHostingView?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        model.onDismiss = { [weak self] in
            self?.panel?.orderOut(nil)
            emit(["event": "dismiss"])
        }
        DispatchQueue.global(qos: .userInitiated).async {
            while let line = readLine() {
                DispatchQueue.main.async {
                    self.handle(line)
                }
            }
        }
    }

    func handle(_ line: String) {
        guard let data = line.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let command = object["cmd"] as? String else { return }
        switch command {
        case "show":
            let text = object["text"] as? String ?? ""
            let language = object["translateLanguage"] as? String
            let editable = object["editable"] as? Bool ?? false
            show(text: text, language: language, editable: editable)
        case "key":
            if let key = object["key"] as? String {
                model.press(key)
            }
        case "dismiss":
            panel?.orderOut(nil)
        default:
            break
        }
    }

    func show(text: String, language: String?, editable: Bool) {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(mouse) } ?? NSScreen.main
        guard let screen else { return }
        if panel == nil || panel?.screen != screen {
            let next = NSPanel(
                contentRect: screen.frame,
                styleMask: [.borderless, .nonactivatingPanel],
                backing: .buffered,
                defer: false
            )
            next.level = .popUpMenu
            next.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            next.isOpaque = false
            next.backgroundColor = .clear
            next.hasShadow = false
            next.hidesOnDeactivate = false
            next.ignoresMouseEvents = false
            next.becomesKeyOnlyIfNeeded = false
            next.isMovable = false
            next.acceptsMouseMovedEvents = true
            let root = MenuRoot(model: model)
            let view = WheelHostingView(rootView: root)
            view.model = model
            view.frame = NSRect(origin: .zero, size: screen.frame.size)
            view.autoresizingMask = [.width, .height]
            next.contentView = view
            host = view
            panel = next
        }
        panel?.setFrame(screen.frame, display: true)
        model.present(text: text, language: language, editable: editable)
        panel?.orderFrontRegardless()
    }
}

private func emit(_ object: [String: Any]) {
    guard JSONSerialization.isValidJSONObject(object),
          let data = try? JSONSerialization.data(withJSONObject: object) else { return }
    var line = data
    line.append(0x0A)
    try? FileHandle.standardOutput.write(contentsOf: line)
}

private func appleIntelligence(_ text: String, proof: Bool) async throws -> String {
    if #available(macOS 26.0, *) {
        return try await Intelligence.run(text, proof: proof)
    }
    throw MenuError("Proofread and Rewrite need Apple Intelligence on macOS 26 or newer.")
}

private struct MenuError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

@available(macOS 26.0, *)
private enum Intelligence {
    static func run(_ text: String, proof: Bool) async throws -> String {
        #if canImport(FoundationModels)
        let model = SystemLanguageModel.default
        switch model.availability {
        case .available:
            break
        case .unavailable(let reason):
            throw MenuError(reasonText(reason))
        }
        let instructions = proof
            ? "Proofread the text. Fix grammar, spelling, and punctuation. Return only the corrected text."
            : "Rewrite the text so it is clearer and more natural. Keep the meaning. Return only the rewritten text."
        let session = LanguageModelSession(instructions: instructions)
        let response = try await session.respond(to: text)
        return response.content.trimmingCharacters(in: .whitespacesAndNewlines)
        #else
        throw MenuError("Apple Intelligence is not available.")
        #endif
    }

    static func reasonText(_ reason: SystemLanguageModel.Availability.UnavailableReason) -> String {
        switch reason {
        case .appleIntelligenceNotEnabled:
            return "Turn on Apple Intelligence in System Settings, then try again."
        case .deviceNotEligible:
            return "This Mac cannot run Apple Intelligence."
        case .modelNotReady:
            return "Apple Intelligence is still getting ready. Try again in a moment."
        @unknown default:
            return "Apple Intelligence is not available."
        }
    }
}

private func startApp() {
    let app = NSApplication.shared
    let controller = MenuController()
    app.delegate = controller
    app.run()
}

startApp()
