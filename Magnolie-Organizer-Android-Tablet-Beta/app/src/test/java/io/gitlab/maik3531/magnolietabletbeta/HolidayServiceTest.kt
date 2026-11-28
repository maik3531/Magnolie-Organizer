package io.gitlab.maik3531.magnolietabletbeta

import java.util.concurrent.CancellationException
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class HolidayServiceTest {
    private class Transport(val handler: (BoundedHttpRequest, DavCancellation) -> BoundedHttpResponse) : BoundedHttpTransport {
        val requests = mutableListOf<BoundedHttpRequest>()
        override fun send(request: BoundedHttpRequest, cancellation: DavCancellation): BoundedHttpResponse {
            cancellation.check(); requests.add(request); return handler(request, cancellation)
        }
    }
    private fun response(vararg rows: JSONObject) = BoundedHttpResponse(200, body = JSONArray(rows.toList()).toString().toByteArray())
    private fun row(start: String = "2028-02-29", end: String = start, name: Any = "Spring") =
        JSONObject().put("startDate", start).put("endDate", end).put("name", name).put("nationwide", false)
    private fun names() = JSONArray().put(JSONObject().put("language", "EN").put("text", "Spring"))
        .put(JSONObject().put("language", "DE").put("text", "Frühling"))
    private fun query(regions: List<HolidayService.Region> = emptyList(), school: Boolean = false) =
        HolidayService.Query("DE", regions, listOf(2028), school)
    private fun message() = JSONObject().put("cmd", "feiertage").put("land", "DE").put("jahre", JSONArray().put(2028))
    private fun fields(request: BoundedHttpRequest) = request.uri.rawQuery.split('&').associate {
        val parts = it.split('=', limit = 2); parts[0] to java.net.URLDecoder.decode(parts[1], "UTF-8")
    }
    private fun expect(code: String, action: () -> Unit) {
        try { action(); fail("Expected $code") } catch (error: HolidayException) { assertEquals(code, error.code) }
    }

    @Test fun canonicalMessageParsesSingleAndAllRegionsWithAuthority() {
        val all = message().put("regionen", JSONArray().put(JSONArray().put("de-be").put("Berlin"))
            .put(JSONObject().put("code", "DE-BB").put("name", "Brandenburg")))
            .put("ferien", true).put("regionErforderlich", true).put("requestId", "request-17")
            .put("session", "host-validated").put("revision", "host-validated")
        val parsed = HolidayService.Query.fromMessage(all, "de-DE")
        assertEquals(listOf("DE-BE", "DE-BB"), parsed.regions.map { it.code })
        assertEquals("DE", parsed.language); assertTrue(parsed.includeSchool); assertEquals("request-17", parsed.requestId)
        val single = HolidayService.Query.fromMessage(all.put("region", "DE-BY"))
        assertEquals(listOf(HolidayService.Region("DE-BY", "")), single.regions)
    }

    @Test fun wrongBridgeTypesAndUnrequestedUrlsAreRejected() {
        for (keyValue in listOf("jahre" to JSONArray().put(true), "jahre" to JSONArray().put(2028.5),
            "jahre" to JSONArray().put("2028"), "jahre" to JSONArray().put(2147483648L),
            "ferien" to "true", "regionErforderlich" to 1, "land" to 123,
            "regionen" to JSONObject(), "regionen" to JSONArray().put(JSONArray().put("DE-BE")),
            "requestId" to 17, "session" to JSONObject.NULL, "url" to "https://example.invalid")) {
            expect("holiday_invalid_query") { HolidayService.Query.fromMessage(message().put(keyValue.first, keyValue.second)) }
        }
    }

    @Test fun queryBoundsNormalizationAndDeduplication() {
        val q = HolidayService.Query(" de ", listOf(HolidayService.Region("de-be", " Berlin "), HolidayService.Region("DE-BE", "Berlin")),
            listOf(2028, 2026, 2028), false, language = "system")
        assertEquals("DE", q.country); assertEquals(listOf(2026, 2028), q.years)
        assertEquals(listOf(HolidayService.Region("DE-BE", "Berlin")), q.regions); assertEquals("DE", q.language)
        for (years in listOf(emptyList(), listOf(0), listOf(10000), listOf(2025, 2026, 2027, 2028)))
            expect("holiday_invalid_query") { HolidayService.Query("DE", years = years, includeSchool = false) }
        for (country in listOf("", "DE/../", "D", "DEU")) expect("holiday_invalid_query") { HolidayService.Query(country, years = listOf(2028), includeSchool = false) }
        expect("holiday_invalid_query") { query(List(27) { HolidayService.Region("DE-$it", "Region $it") }) }
        expect("holiday_invalid_query") { query(listOf(HolidayService.Region("DE&countryIsoCode=US", "Berlin"))) }
    }

    @Test fun fixedOriginEndpointLanguageAndInclusiveLeapDates() {
        val transport = Transport { request, _ ->
            val school = request.uri.path == "/SchoolHolidays"
            response(row(end = if (school) "2028-03-04" else "2028-02-29", name = names())
                .put("nationwide", !school).put("subdivisions", JSONArray().also { if (school) it.put(JSONObject().put("code", "DE-BE")) }))
        }
        val query = HolidayService.Query("de", listOf(HolidayService.Region("DE-BE", "Berlin")), listOf(2028), true, true, "de-DE", "req-1")
        val result = HolidayService(transport).fetch(query)
        assertEquals(2, result.entries.size); assertTrue(result.entries.all { it.name == "Frühling" })
        val school = result.entries.single { it.kind == "school-holiday" }
        assertEquals("2028-02-29", school.start); assertEquals("2028-03-04", school.end)
        assertEquals(listOf("DE-BE"), school.regions); assertEquals("Berlin", school.regionLabel)
        assertEquals(listOf("/PublicHolidays", "/SchoolHolidays"), transport.requests.map { it.uri.path })
        for (request in transport.requests) {
            assertEquals("https", request.uri.scheme); assertEquals("openholidaysapi.org", request.uri.host)
            assertEquals("GET", request.method); assertFalse(request.headers.keys.any { it.equals("Authorization", true) })
            assertTrue(request.timeoutMillis in 1..20_000); assertEquals(2 * 1024 * 1024, request.maxResponseBytes)
            assertEquals(mapOf("countryIsoCode" to "DE", "languageIsoCode" to "DE", "validFrom" to "2028-01-01", "validTo" to "2028-12-31", "subdivisionCode" to "DE-BE"), fields(request))
        }
        val callback = result.callbackValue()
        assertEquals("req-1", callback.getString("requestId")); assertEquals(2028, callback.getJSONArray("jahre").getInt(0))
        assertEquals("2028-03-04", (0 until 2).map { callback.getJSONArray("feiertage").getJSONObject(it) }
            .single { it.getString("art") == "school-holiday" }.getString("bis"))
        assertFalse(callback.has("fehler")); assertTrue(callback.getString("bericht").contains("2028"))
    }

    @Test fun missingSchoolRegionStillFetchesCountryPublicHolidays() {
        val transport = Transport { _, _ -> response() }
        val q = HolidayService.Query("CH", years = listOf(2028), includeSchool = true, regionRequired = true)
        assertFalse(q.includeSchool)
        assertTrue(HolidayService(transport).fetch(q).entries.isEmpty())
        assertEquals(1, transport.requests.size); assertEquals("/PublicHolidays", transport.requests.single().uri.path)
        assertFalse(fields(transport.requests.single()).containsKey("subdivisionCode"))
    }

    // Refs #856: OpenHolidays /Subdivisions AT fixture, retrieved 2026-11-28.
    // Provider codes are not ISO 3166-2; settings/cache identities remain ISO.
    private val austrianProviders = linkedMapOf("AT-1" to "AT-BL", "AT-2" to "AT-KÄ",
        "AT-3" to "AT-NÖ", "AT-4" to "AT-OÖ", "AT-5" to "AT-SB", "AT-6" to "AT-SM",
        "AT-7" to "AT-TI", "AT-8" to "AT-VA", "AT-9" to "AT-WI")

    @Test fun austrianQueriesTranslateAllNineIsoCodesAndEncodeProviderUnicode() {
        for ((iso, provider) in austrianProviders) {
            val transport = Transport { _, _ -> response(row().put("nationwide", true)) }
            val q = HolidayService.Query("AT", listOf(HolidayService.Region(iso, "Fixture region")),
                listOf(2028), true)
            val result = HolidayService(transport).fetch(q)
            assertEquals(listOf(iso), q.regions.map { it.code })
            assertEquals(2, transport.requests.size)
            for (request in transport.requests) {
                assertEquals(provider, fields(request).getValue("subdivisionCode"))
                assertTrue(request.uri.rawQuery.contains("subdivisionCode=" + java.net.URLEncoder.encode(provider, "UTF-8")))
                assertTrue(request.uri.toASCIIString().all { it.code < 128 })
            }
            assertEquals(listOf(iso, iso), result.coverage.map { it.region })
            assertTrue(result.entries.all { it.selectedRegions == listOf(iso) })
        }
    }

    @Test fun austrianProviderRepliesBecomeCanonicalIsoBeforeCoverageChecks() {
        for ((iso, provider) in austrianProviders) for (returned in listOf(provider, iso)) {
            val transport = Transport { _, _ -> response(row().put("subdivisions",
                JSONArray().put(JSONObject().put("code", returned)))) }
            val result = HolidayService(transport).fetch(HolidayService.Query("AT",
                listOf(HolidayService.Region(iso, "Fixture region")), listOf(2028), false))
            assertEquals(listOf(iso), result.entries.single().regions)
            assertEquals(listOf(iso), result.entries.single().selectedRegions)
            assertEquals(iso, result.coverage.single().region)
            assertEquals(iso, result.callbackValue().getJSONArray("feiertage").getJSONObject(0)
                .getJSONArray("regions").getString(0))
        }
    }

    @Test fun austrianSharedPeriodsKeepAllCanonicalRegionsAndDeduplicateSelections() {
        val transport = Transport { _, _ -> response(row().put("subdivisions", JSONArray()
            .put(JSONObject().put("code", "AT-NÖ")).put(JSONObject().put("code", "AT-WI")))) }
        val q = HolidayService.Query("AT", listOf(HolidayService.Region("AT-3", "Lower Austria"),
            HolidayService.Region("AT-9", "Vienna")), listOf(2028), true)
        val result = HolidayService(transport).fetch(q)
        assertEquals(2, result.entries.size)
        assertTrue(result.entries.all { it.regions == listOf("AT-3", "AT-9") &&
            it.selectedRegions == listOf("AT-3", "AT-9") })
        assertEquals(listOf("AT-3", "AT-9", "AT-3", "AT-9"), result.coverage.map { it.region })
    }

    @Test fun unknownAustrianQueryNeverStartsHttp() {
        for (code in listOf("AT-0", "AT-10", "AT-UNKNOWN", "AT-WI", "DE-SN")) {
            val transport = Transport { _, _ -> response() }
            expect("holiday_invalid_query") {
                HolidayService(transport).fetch(HolidayService.Query("AT",
                    listOf(HolidayService.Region(code, "Unknown")), listOf(2028), true))
            }
            assertTrue(transport.requests.isEmpty())
        }
    }

    @Test fun unknownAndForeignAustrianReplyCodesNeverCertifyCacheReplacement() {
        for (code in listOf("AT-UNKNOWN", "AT-10", "AT-9-UNKNOWN", "DE-SN", "UNKNOWN")) {
            val result = HolidayService(Transport { _, _ -> response(row().put("subdivisions",
                JSONArray().put(JSONObject().put("code", "AT-9")).put(JSONObject().put("code", code)))) }).fetch(HolidayService.Query("AT",
                listOf(HolidayService.Region("AT-9", "Vienna")), listOf(2028), false))
            assertTrue(result.coverage.isEmpty())
        }
        expect("holiday_invalid_response") {
            HolidayService(Transport { _, _ -> response(row().put("subdivisions",
                JSONArray().put(JSONObject().put("code", "AT-ÄUNKNOWN")))) }).fetch(HolidayService.Query("AT",
                listOf(HolidayService.Region("AT-9", "Vienna")), listOf(2028), false))
        }
    }

    @Test fun austrianEmptyOptOutCountryAndSwissQueriesKeepTheirCoverageBoundaries() {
        for ((country, selected) in listOf("AT" to "AT-2", "AT" to "", "CH" to "CH-ZH")) {
            val transport = Transport { _, _ -> response() }
            val result = HolidayService(transport).fetch(HolidayService.Query(country,
                if (selected.isEmpty()) emptyList() else listOf(HolidayService.Region(selected, "Fixture")),
                listOf(2028), false))
            assertEquals(1, transport.requests.size)
            assertEquals("/PublicHolidays", transport.requests.single().uri.path)
            assertEquals(selected, result.coverage.single().region)
            assertEquals("public-holiday", result.coverage.single().kind)
            assertEquals(when (selected) { "" -> null; "AT-2" -> "AT-KÄ"; else -> selected },
                fields(transport.requests.single())["subdivisionCode"])
        }
    }

    @Test fun successfulEmptyResponsesCertifyOnlyTheirActualRequestedScopes() {
        val transport = Transport { _, _ -> response() }
        val q = HolidayService.Query("DE", listOf(HolidayService.Region("DE-BE", "Berlin"),
            HolidayService.Region("DE-BB", "Brandenburg")), listOf(2028, 2027), true, true, requestId = "coverage-1")
        val result = HolidayService(transport).fetch(q)
        assertTrue(result.entries.isEmpty()); assertEquals(8, result.coverage.size)
        val expected = transport.requests.map { request ->
            val f = fields(request)
            listOf(f.getValue("countryIsoCode"), f.getValue("subdivisionCode"),
                if (request.uri.path == "/SchoolHolidays") "school-holiday" else "public-holiday",
                f.getValue("validFrom"), f.getValue("validTo"))
        }
        assertEquals(expected, result.coverage.map { listOf(it.country, it.region, it.kind, it.start, it.end) })
        val callback = result.callbackValue()
        assertEquals("coverage-1", callback.getString("requestId"))
        val scopes = callback.getJSONArray("abrufbereiche")
        assertEquals(expected, (0 until scopes.length()).map { index ->
            val value = scopes.getJSONObject(index)
            listOf("country", "region", "art", "von", "bis").map(value::getString)
        })
    }

    @Test fun schoolOptOutAndMissingRequiredRegionNeverCertifySchoolScopes() {
        for (q in listOf(query(listOf(HolidayService.Region("DE-BE", "Berlin")), school = false),
            HolidayService.Query("CH", years = listOf(2028), includeSchool = true, regionRequired = true))) {
            val result = HolidayService(Transport { _, _ -> response() }).fetch(q)
            assertEquals(1, result.coverage.size)
            assertEquals("public-holiday", result.coverage.single().kind)
            assertEquals(q.regions.singleOrNull()?.code.orEmpty(), result.coverage.single().region)
        }
    }

    @Test fun toleratedMalformedMetadataNeverCertifiesCacheReplacement() {
        val regions = listOf(HolidayService.Region("DE-BE", "Berlin"))
        for (bad in listOf(row().put("nationwide", "true"), row().put("nationwide", JSONObject.NULL),
            row(end = ""), row().put("endDate", JSONObject.NULL), row().put("subdivisions", JSONObject.NULL),
            row().also { it.remove("endDate") }, row().also { it.remove("nationwide") },
            row(name = JSONArray().put(JSONObject().put("language", "EN").put("text", "Spring")).put(JSONObject())))) {
            val result = HolidayService(Transport { _, _ -> response(bad) }).fetch(query(regions))
            assertEquals(1, result.entries.size)
            assertTrue(result.coverage.isEmpty())
            assertEquals(0, result.callbackValue().getJSONArray("abrufbereiche").length())
        }
        val partial = HolidayService(Transport { request, _ ->
            if (request.uri.path == "/SchoolHolidays") response(row().put("nationwide", "true")) else response()
        }).fetch(query(regions, school = true))
        assertEquals(listOf("public-holiday"), partial.coverage.map { it.kind })
        assertEquals("school-holiday", partial.entries.single().kind)
    }

    @Test fun unrelatedYearsOrRegionsNeverCertifyTheRequestedScope() {
        val q = query(listOf(HolidayService.Region("DE-BE", "Berlin")))
        for (bad in listOf(row("2027-12-25"),
            row().put("subdivisions", JSONArray().put(JSONObject().put("code", "AT-9"))),
            row().put("subdivisions", JSONArray().put(JSONObject().put("code", "DE-BY"))))) {
            val result = HolidayService(Transport { _, _ -> response(bad) }).fetch(q)
            assertEquals(1, result.entries.size); assertTrue(result.coverage.isEmpty())
        }
        for (code in listOf("DE-BE-TEST", "BE")) {
            val matching = row().put("subdivisions", JSONArray().put(JSONObject().put("code", code)))
            val result = HolidayService(Transport { _, _ -> response(matching) }).fetch(q)
            assertEquals("DE-BE", result.coverage.single().region)
        }
        val unknown = HolidayService(Transport { _, _ -> response(row()) }).fetch(query())
        assertEquals(1, unknown.entries.size); assertTrue(unknown.coverage.isEmpty())
    }

    @Test fun groupedRowsRetainEveryFallbackRegionAndNationwideBoolean() {
        val regions = listOf(HolidayService.Region("DE-BE", "Berlin"), HolidayService.Region("DE-BB", "Brandenburg"))
        val transport = Transport { _, _ -> response(row().put("nationwide", "true")) }
        val entry = HolidayService(transport).fetch(query(regions)).entries.single()
        assertEquals(listOf("DE-BB", "DE-BE"), entry.regions)
        assertEquals(listOf("DE-BB", "DE-BE"), entry.selectedRegions)
        assertFalse(entry.nationwide); assertEquals("Spring (all states)", entry.name)
        assertEquals("all states", entry.organizerValue().getString("regionName"))
        assertEquals("DE-BB,DE-BE", entry.organizerValue().getString("region"))
        val national = HolidayService(Transport { _, _ -> response(row().put("nationwide", true)) }).fetch(query(regions)).entries.single()
        assertTrue(national.nationwide); assertTrue(national.regions.isEmpty())
    }

    @Test fun providerScopesUnionAndAllExceptLabelsPreserveSelection() {
        val regions = listOf(HolidayService.Region("DE-BE", "Berlin"), HolidayService.Region("DE-BB", "Brandenburg"), HolidayService.Region("DE-BY", "Bayern"))
        val transport = Transport { request, _ ->
            if (fields(request)["subdivisionCode"] == "DE-BY") response()
            else response(row().put("subdivisions", JSONArray().put(JSONObject().put("code", fields(request)["subdivisionCode"]))))
        }
        val entry = HolidayService(transport).fetch(query(regions)).entries.single()
        assertEquals("Spring (all except Bayern)", entry.name)
        assertEquals("all except Bayern", entry.regionLabel)
        assertEquals(listOf("DE-BB", "DE-BE"), entry.regions)
    }

    @Test fun canonicalNamesMergeAndLanguageFallsBackToFirstNonempty() {
        var n = 0
        val regions = listOf(HolidayService.Region("CH-BE", "Bern"), HolidayService.Region("CH-ZH", "Zürich"))
        val transport = Transport { _, _ -> response(row(name = if (n++ == 0) "Straße Fête" else "STRASSE  FETE")) }
        val q = HolidayService.Query("CH", regions, listOf(2028), false, language = "de")
        val entry = HolidayService(transport).fetch(q).entries.single()
        assertEquals("Straße Fête (alle Kantone)", entry.name)
        val fallback = JSONArray().put(JSONObject().put("language", "FR").put("text", " "))
            .put(JSONObject().put("language", "FR").put("text", "Fête"))
        val result = HolidayService(Transport { _, _ -> response(row(name = fallback)) }).fetch(query())
        assertEquals("Fête", result.entries.single().name)
    }

    @Test fun wrapperDatesAndDeterministicOrdering() {
        val transport = Transport { _, _ -> BoundedHttpResponse(200, body = JSONObject().put("data", JSONArray()
            .put(row("2028-12-25", name = "Winter")).put(row("2028-01-01T00:00:00", "", "New Year"))).toString().toByteArray()) }
        val entries = HolidayService(transport).fetch(query()).entries
        assertEquals(listOf("2028-01-01", "2028-12-25"), entries.map { it.start })
        assertEquals("2028-01-01", entries.first().end)
    }

    @Test fun failedSchoolOrLaterYearReturnsNoPartialResultAndNoPersistentCache() {
        var count = 0
        val transport = Transport { _, _ -> if (++count == 2) BoundedHttpResponse(503) else response(row()) }
        val service = HolidayService(transport)
        expect("holiday_http_error") { service.fetch(query(school = true)) }
        // A subsequent empty response must not reuse the first request's successful public rows.
        val empty = HolidayService(Transport { _, _ -> response() }).fetch(query())
        assertTrue(empty.entries.isEmpty()); assertFalse(empty.callbackValue().has("requestId"))
    }

    @Test fun redirectsAndMalformedDataCannotProducePartialRows() {
        val bad = listOf(BoundedHttpResponse(302, mapOf("Location" to "https://example.invalid")),
            BoundedHttpResponse(503), BoundedHttpResponse(200, body = "not-json".toByteArray()),
            BoundedHttpResponse(200, body = "[] trailing".toByteArray()),
            BoundedHttpResponse(200, body = byteArrayOf(0xC3.toByte(), 0x28)),
            BoundedHttpResponse(200, body = "{\"data\":{}}".toByteArray()),
            response(row("2027-02-29")), response(row(end = "2028-02-28")),
            response(row(), row(name = "")), response(row().put("subdivisions", "DE-BE")),
            response(row().put("subdivisions", JSONArray().put(JSONObject().put("code", "../bad")))))
        for (response in bad) {
            try { HolidayService(Transport { _, _ -> response }).fetch(query()); fail("Invalid response accepted") }
            catch (_: HolidayException) { /* No Result exists, so the caller cannot apply a successful subset. */ }
        }
    }

    @Test fun responseByteTotalRowAndDepthLimitsAreEnforced() {
        expect("holiday_response_too_large") {
            HolidayService(Transport { _, _ -> BoundedHttpResponse(200, body = ByteArray(2 * 1024 * 1024 + 1)) }).fetch(query())
        }
        val padded = "[]".padEnd(2 * 1024 * 1024).toByteArray()
        val transport = Transport { _, _ -> BoundedHttpResponse(200, body = padded) }
        val q = HolidayService.Query("DE", (0..8).map { HolidayService.Region("DE-$it", "Region $it") }, listOf(2028), false)
        expect("holiday_response_too_large") { HolidayService(transport).fetch(q) }
        assertEquals(9, transport.requests.size)
        val rows = JSONArray(); repeat(10_001) { rows.put(row()) }
        expect("holiday_response_too_large") { HolidayService(Transport { _, _ -> BoundedHttpResponse(200, body = rows.toString().toByteArray()) }).fetch(query()) }
        val deep = "[".repeat(40) + "]".repeat(40)
        expect("holiday_invalid_response") { HolidayService(Transport { _, _ -> BoundedHttpResponse(200, body = deep.toByteArray()) }).fetch(query()) }
    }

    @Test fun totalDeadlineBoundsLaterRequestAndRejectsItsLateResponse() {
        var now = 0L; var count = 0
        val transport = Transport { _, _ -> now += if (++count == 1) 88_000_000_000L else 3_000_000_000L; response(row()) }
        expect("holiday_timeout") { HolidayService(transport) { now }.fetch(query(school = true)) }
        assertEquals(listOf(20_000L, 2_000L), transport.requests.map { it.timeoutMillis })
    }

    @Test fun cancellationBeforeAndDuringTransportNeverPublishesData() {
        val token = DavCancellation().also { it.cancel() }
        val transport = Transport { _, _ -> response(row()) }
        try { HolidayService(transport).fetch(query(), token); fail("Cancelled query completed") } catch (_: CancellationException) {}
        assertTrue(transport.requests.isEmpty())
        val during = Transport { _, cancellation -> cancellation.cancel(); response(row()) }
        try { HolidayService(during).fetch(query()); fail("Cancelled response accepted") } catch (_: CancellationException) {}
    }

    @Test fun transportErrorsExposeNoRemoteOrSensitiveMessage() {
        expect("holiday_transport_error") {
            HolidayService(Transport { _, _ -> throw IllegalStateException("remote private payload") }).fetch(query())
        }
        expect("holiday_timeout") {
            HolidayService(Transport { _, _ -> throw DavException("timeout") }).fetch(query())
        }
    }

    @Test fun deadlineAndCancellationAlsoFenceJsonParsing() {
        var clockCalls = 0
        val transport = Transport { _, _ -> response(row()) }
        expect("holiday_timeout") {
            HolidayService(transport) { if (++clockCalls >= 5) 91_000_000_000L else 0L }.fetch(query())
        }
        val token = DavCancellation()
        clockCalls = 0
        try {
            HolidayService(transport) { if (++clockCalls == 5) token.cancel(); 0L }.fetch(query(), token)
            fail("Cancellation during parsing accepted")
        } catch (_: CancellationException) {}
    }
}
