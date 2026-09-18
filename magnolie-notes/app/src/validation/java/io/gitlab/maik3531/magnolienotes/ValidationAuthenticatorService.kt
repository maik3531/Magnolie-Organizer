package io.gitlab.maik3531.magnolienotes

import android.accounts.*
import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.IBinder

/** Opt-in validation account owner for the isolated native ContactsProvider fixture. */
class ValidationAuthenticatorService : Service() {
    override fun onBind(intent: Intent?): IBinder? {
        if (!packageName.endsWith(".validation")) return null
        return object : AbstractAccountAuthenticator(this) {
            override fun editProperties(response: AccountAuthenticatorResponse?, accountType: String?) = Bundle.EMPTY
            override fun addAccount(response: AccountAuthenticatorResponse?, accountType: String?, authTokenType: String?,
                                    requiredFeatures: Array<out String>?, options: Bundle?) = Bundle.EMPTY
            override fun confirmCredentials(response: AccountAuthenticatorResponse?, account: Account?, options: Bundle?) = Bundle.EMPTY
            override fun getAuthToken(response: AccountAuthenticatorResponse?, account: Account?, authTokenType: String?, options: Bundle?) = Bundle.EMPTY
            override fun getAuthTokenLabel(authTokenType: String?) = ""
            override fun updateCredentials(response: AccountAuthenticatorResponse?, account: Account?, authTokenType: String?, options: Bundle?) = Bundle.EMPTY
            override fun hasFeatures(response: AccountAuthenticatorResponse?, account: Account?, features: Array<out String>?) =
                Bundle().apply { putBoolean(AccountManager.KEY_BOOLEAN_RESULT, false) }
        }.iBinder
    }
}
