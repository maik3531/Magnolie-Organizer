#!/usr/bin/env python3
"""Compile actual Kotlin acquisition bodies on the JVM with bounded fake sockets.

This checks ownership/cleanup, not Android, DNS, Bluetooth or real socket behavior.
Compiler/library paths must refer to already installed/cached tools; no downloads.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'app/src/main/java/io/gitlab/maik3531/magnolienotes'

PRELUDE = r'''
import java.io.*
import java.net.InetAddress
import java.net.InetSocketAddress
import kotlinx.serialization.json.*
import io.gitlab.maik3531.magnolienotes.netz.LanTor

interface Transport {
    val bezeichnung: String
    fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject
    fun schliessen()
}
interface TelefonRoehre: AutoCloseable {
    val input: InputStream
    val output: OutputStream
    fun setReadTimeout(timeoutMs: Int)
    fun aktuell(): Boolean = true
    fun pruefen() { if (!aktuell()) throw IOException("retired") }
}
object TelefonParameter { const val PORT = 8738 }
class BaumFehler(message: String, val httpStatus: Int = 0): IOException(message)
class KeineVerbindung(error: Exception): IOException(error)
fun verbindungAbgelehnt(error: java.net.ConnectException) = false
object Kanonisch { val json = Json }
object Netz {
    fun hostPortAnzeigen(host: String, port: Int) = "$host:$port"
    fun fehlertext(code: Int, text: String) = "$code $text"
}
class Socket: AutoCloseable {
    companion object { var opened = 0; var closed = 0; var connected = 0 }
    private var ended = false
    var soTimeout = 0
    val inetAddress: InetAddress = InetAddress.getByAddress(byteArrayOf(127,0,0,1))
    val localAddress: InetAddress get() = inetAddress
    val isClosed: Boolean get() = ended
    init { opened++ }
    fun connect(address: InetSocketAddress, timeout: Int) { check(!ended); connected++ }
    fun bind(address: InetSocketAddress) { check(!ended) }
    fun getOutputStream() = ByteArrayOutputStream()
    fun getInputStream() = ByteArrayInputStream("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}".toByteArray())
    override fun close() { if (!ended) { ended = true; closed++ } }
}
class ServerSocket(port: Int, backlog: Int): AutoCloseable {
    companion object { var opened = 0; var closed = 0 }
    private var ended = false
    init { opened++ }
    override fun close() { if (!ended) { ended = true; closed++ } }
}
object LanFreigabe {
    const val WARTET = "synthetic LAN denial"
    var grant = true
    var denyRegistration = false
    var throwRegistration = false
    private var gate = LanTor { grant }
    fun reset() { grant = true; denyRegistration = false; throwRegistration = false; gate = LanTor { grant } }
    fun erlaubt() = gate.erlaubt()
    fun pruefen() { if (!erlaubt()) throw IOException(WARTET) }
    fun marke(): Long { pruefen(); return gate.marke() }
    fun aktuell(token: Long) = gate.aktuell(token)
    fun ziel(host: String): InetAddress { pruefen(); return InetAddress.getByAddress(byteArrayOf(127,0,0,1)) }
    fun lokal(address: InetAddress) = true
    fun beobachten(resource: AutoCloseable): AutoCloseable {
        if (throwRegistration) throw IOException("synthetic registration failure")
        if (denyRegistration) { denyRegistration = false; grant = false }
        return try { gate.beobachten(resource) } catch (error: IllegalStateException) { throw IOException(WARTET, error) }
    }
    class ZielWache(private val registration: AutoCloseable) : AutoCloseable {
        fun pruefen() { LanFreigabe.pruefen() }
        override fun close() { registration.close() }
    }
    fun beobachtenZiel(address: InetAddress, resource: AutoCloseable) = ZielWache(beobachten(resource))
}
'''

TESTS = r'''
fun main() {
    LanFreigabe.reset()
    val transport = WlanTransport("synthetic.local", 8737)
    LanFreigabe.denyRegistration = true
    check(runCatching { transport.anfrage("/synthetic", JsonObject(emptyMap()), 1000) }.isFailure)
    check(Socket.opened == 1 && Socket.closed == 1 && Socket.connected == 0)
    LanFreigabe.grant = true
    check(transport.anfrage("/synthetic", JsonObject(emptyMap()), 1000).isEmpty())
    check(Socket.opened == 2 && Socket.closed == 2 && Socket.connected == 1)
    // Unexpected registration errors also unwind ownership before a later retry.
    LanFreigabe.throwRegistration = true
    check(runCatching { transport.anfrage("/synthetic", JsonObject(emptyMap()), 1000) }.isFailure)
    LanFreigabe.throwRegistration = false
    check(transport.anfrage("/synthetic", JsonObject(emptyMap()), 1000).isEmpty())
    check(Socket.opened == Socket.closed)
    transport.schliessen()

    LanFreigabe.reset(); LanFreigabe.grant = false
    check(runCatching { InvitationOwner() }.isFailure)
    check(ServerSocket.opened == 0) // token denial must precede resource acquisition
    LanFreigabe.reset(); LanFreigabe.throwRegistration = true
    check(runCatching { InvitationOwner() }.isFailure)
    check(ServerSocket.opened == 1 && ServerSocket.closed == 1)
    LanFreigabe.reset(); LanFreigabe.denyRegistration = true
    check(runCatching { InvitationOwner() }.isFailure)
    check(ServerSocket.opened == 2 && ServerSocket.closed == 2)
    LanFreigabe.reset(); InvitationOwner().release()
    check(ServerSocket.opened == 3 && ServerSocket.closed == 3)
    LanFreigabe.reset(); LanFreigabe.throwRegistration = true
    check(runCatching { TelefonTcpRoehre("127.0.0.1", 1000) }.isFailure)
    check(Socket.opened == Socket.closed)
    LanFreigabe.reset(); LanFreigabe.denyRegistration = true
    check(runCatching { TelefonTcpRoehre("127.0.0.1", 1000) }.isFailure)
    check(Socket.opened == Socket.closed)
    LanFreigabe.reset(); LanFreigabe.grant = false
    val connected = Socket.connected
    check(runCatching { TelefonTcpRoehre("127.0.0.1", 1000) }.isFailure)
    check(Socket.opened == Socket.closed && Socket.connected == connected)
    LanFreigabe.reset(); TelefonTcpRoehre("127.0.0.1", 1000).close()
    check(Socket.opened == Socket.closed)
    println("PASS actual Kotlin ownership bodies: denied registration/regrant/reuse, unexpected registration failure, invitation acquisition boundaries; fake sockets, no Android acceptance")
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler-classpath', required=True)
    parser.add_argument('--libraries', required=True, help='Existing Kotlin stdlib and serialization jars, separated by OS path separator')
    parser.add_argument('--java', default='java')
    parser.add_argument('--javac', default='javac')
    args = parser.parse_args()
    for name in (args.compiler_classpath + os.pathsep + args.libraries).split(os.pathsep):
        assert Path(name).is_file(), name
    text = (SRC / 'baum/Transport.kt').read_text()
    start = text.index('class WlanTransport(')
    transport = text[start:text.index('\n}\n', start) + 3]
    invitation = (SRC / 'telefon/TelefonEinladung.kt').read_text()
    begin = invitation.index('    private val lanMarke =')
    fields = invitation[begin:invitation.index('    val port:', begin)]
    owner = '\nclass InvitationOwner {\n' + fields + '\nfun release() { lanWache.close(); listener.close() }\n}\n'
    tcp_source = (SRC / 'telefon/TelefonBluetooth.kt').read_text()
    begin = tcp_source.index('internal class TelefonTcpRoehre(')
    tcp = tcp_source[begin:tcp_source.index('\n}\n', begin) + 3]
    with tempfile.TemporaryDirectory(prefix='magnolie-lan-ownership-') as folder:
        root = Path(folder); classes = root / 'classes'; classes.mkdir()
        subprocess.run([args.javac, '--release', '17', '-d', str(classes), str(SRC / 'netz/LanTor.java')], check=True, timeout=30)
        libraries = str(classes) + os.pathsep + args.libraries
        for variant in ('current', 'broken-wlan', 'broken-invitation', 'broken-tcp'):
            body, declarations, tcp_body = transport, owner, tcp
            if variant == 'broken-wlan':
                line = '            val wache = LanFreigabe.beobachtenZiel(ziel, verbindung)\n            lanWache = wache\n'
                assert body.count(line) == 1
                body = body.replace(line, '').replace('            try {\n', line + '            try {\n', 1)
            if variant == 'broken-invitation':
                token = '    private val lanMarke = LanFreigabe.marke()\n'
                listener = '    private val listener = ServerSocket(0, 1)\n'
                assert token + listener in declarations
                declarations = declarations.replace(token + listener, listener + token)
            if variant == 'broken-tcp':
                old = '    private val lanWache = try { LanFreigabe.beobachten(socket) }\n        catch (error: Exception) { runCatching { socket.close() }; throw error }'
                assert old in tcp_body
                tcp_body = tcp_body.replace(old, '    private val lanWache = LanFreigabe.beobachten(socket)')
            source = root / 'Ownership.kt'; source.write_text(PRELUDE + body + declarations + tcp_body + TESTS)
            target = root / variant; target.mkdir()
            result = subprocess.run([args.java, '-Xmx512m', '-cp', args.compiler_classpath,
                'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect', '-jvm-target', '17',
                '-classpath', libraries, '-d', str(target), str(source)], text=True, capture_output=True, timeout=90)
            assert result.returncode == 0, result.stdout + result.stderr
            result = subprocess.run([args.java, '-cp', str(target) + os.pathsep + libraries, 'OwnershipKt'],
                                    text=True, capture_output=True, timeout=30)
            if variant == 'current':
                assert result.returncode == 0, result.stdout + result.stderr
                print(result.stdout.strip())
            else:
                assert result.returncode != 0 and 'Check failed' in result.stderr, result.stdout + result.stderr
                print('PASS mutation rejected: ' + variant)


if __name__ == '__main__':
    main()
