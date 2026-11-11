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
    var onDismiss: () -> Void = {}
    private var job = 0
    private var anchor = CGPoint.zero

    func present(text: String, language: String?) {
        job += 1
        sourceText = text
        translateLanguage = language
        showLanguages = false
        languagesOpened = false
        busyTitle = nil
        previewTitle = nil
        previewText = nil
        errorText = nil
        translationConfig = nil
        anchor = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(anchor) } ?? NSScreen.main
        screenFrame = screen?.frame ?? .zero
        center = shifted(anchor, radius: 118, screen: screen)
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
                let screen = NSScreen.screens.first { $0.frame.contains(anchor) } ?? NSScreen.main
                center = shifted(anchor, radius: 196, screen: screen)
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
        var config = TranslationSession.Configuration(
            source: nil,
            target: Locale.Language(identifier: code)
        )
        config.invalidate()
        translationConfig = config
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

struct MenuRoot: View {
    @ObservedObject var model: MenuModel

    var body: some View {
        GeometryReader { geo in
            let local = localPoint(model.center, in: geo.size)
            ZStack {
                Color.clear
                    .contentShape(Rectangle())
                    .onTapGesture {
                        model.dismiss()
                    }
                buttons(
                    actions.map { ($0.id, $0.title, $0.symbol, $0.key) },
                    radius: 118,
                    sprung: model.opened,
                    at: local
                ) { id in
                    model.run(id)
                }
                if model.showLanguages {
                    buttons(
                        languages.enumerated().map { index, language in
                            (language.id, language.title, "character.bubble", String(index + 1))
                        },
                        radius: 196,
                        sprung: model.languagesOpened,
                        at: local
                    ) { id in
                        model.chooseLanguage(id)
                    }
                }
                if let busy = model.busyTitle {
                    card(title: busy, text: nil, at: local, offset: 168, in: geo.size)
                } else if let text = model.previewText {
                    card(title: model.previewTitle ?? "Result", text: text, at: local, offset: 168, in: geo.size)
                } else if let error = model.errorText {
                    card(title: "Could not finish", text: error, at: local, offset: 168, in: geo.size)
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

    private func localPoint(_ point: CGPoint, in size: CGSize) -> CGPoint {
        let origin = model.screenFrame.origin
        return CGPoint(
            x: point.x - origin.x,
            y: size.height - (point.y - origin.y)
        )
    }

    private func buttons(
        _ items: [(String, String, String, String)],
        radius: CGFloat,
        sprung: Bool,
        at center: CGPoint,
        onTap: @escaping (String) -> Void
    ) -> some View {
        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
            let count = CGFloat(max(items.count, 1))
            let angle = (CGFloat.pi / 2) - (CGFloat(index) * (2 * CGFloat.pi / count))
            Orb(title: item.1, symbol: item.2, key: item.3) {
                onTap(item.0)
            }
            .scaleEffect(sprung ? 1 : 0.15)
            .position(
                x: center.x + (sprung ? cos(angle) * radius : 0),
                y: center.y + (sprung ? sin(angle) * radius : 0)
            )
            .animation(
                .spring(response: 0.42, dampingFraction: 0.68).delay(0.045 * Double(index)),
                value: sprung
            )
        }
    }

    @ViewBuilder
    private func card(title: String, text: String?, at center: CGPoint, offset: CGFloat, in size: CGSize) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
            if let text {
                Text(text)
                    .font(.system(size: 13))
                    .lineLimit(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ProgressView()
                    .controlSize(.small)
            }
            if model.previewText != nil {
                HStack(spacing: 8) {
                    Button("Replace") { model.replace() }
                    Button("Copy") { model.copy() }
                }
            }
        }
        .padding(14)
        .frame(width: 280)
        .modifier(GlassChrome(shape: RoundedRectangle(cornerRadius: 18, style: .continuous)))
        .position(x: min(max(center.x, 150), max(size.width - 150, 150)), y: cardY(center.y, offset: offset, height: size.height))
    }

    private func cardY(_ y: CGFloat, offset: CGFloat, height: CGFloat) -> CGFloat {
        let below = y + offset
        if below + 90 < height {
            return below
        }
        return max(90, y - offset)
    }
}

struct Orb: View {
    let title: String
    let symbol: String
    let key: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: 2) {
                Image(systemName: symbol)
                    .font(.system(size: 18, weight: .semibold))
                Text(title)
                    .font(.system(size: 10, weight: .medium))
                    .lineLimit(1)
                Text(key)
                    .font(.system(size: 9, weight: .semibold))
                    .opacity(0.7)
            }
            .frame(width: 76, height: 76)
            .modifier(GlassChrome(shape: Circle()))
            .scaleEffect(hover ? 1.16 : 1)
            .animation(.spring(response: 0.22, dampingFraction: 0.7), value: hover)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

struct GlassChrome<S: Shape>: ViewModifier {
    let shape: S

    func body(content: Content) -> some View {
        Group {
            if #available(macOS 26.0, *) {
                content.glassEffect(.regular, in: shape)
            } else {
                content.background(.thinMaterial, in: shape)
            }
        }
    }
}

final class HitHostingView<Content: View>: NSHostingView<Content> {
    var onBackgroundClick: (() -> Void)?

    override func hitTest(_ point: NSPoint) -> NSView? {
        let hit = super.hitTest(point)
        if hit == nil || hit === self {
            return self
        }
        return hit
    }

    override func mouseDown(with event: NSEvent) {
        onBackgroundClick?()
    }

    override func rightMouseDown(with event: NSEvent) {
        onBackgroundClick?()
    }
}

final class MenuController: NSObject, NSApplicationDelegate {
    let model = MenuModel()
    var panel: NSPanel?
    var host: HitHostingView<MenuRoot>?

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
            show(text: text, language: language)
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

    func show(text: String, language: String?) {
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
            next.isMovable = false
            next.acceptsMouseMovedEvents = true
            let root = MenuRoot(model: model)
            let view = HitHostingView(rootView: root)
            view.onBackgroundClick = { [weak self] in
                self?.model.dismiss()
            }
            view.frame = NSRect(origin: .zero, size: screen.frame.size)
            view.autoresizingMask = [.width, .height]
            next.contentView = view
            host = view
            panel = next
        }
        panel?.setFrame(screen.frame, display: true)
        model.present(text: text, language: language)
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
