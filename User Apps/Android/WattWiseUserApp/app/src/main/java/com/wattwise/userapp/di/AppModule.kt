package com.wattwise.userapp.di

import com.wattwise.userapp.data.remote.WattWiseApiService
import com.wattwise.userapp.data.remote.WattWiseAuthApi
import com.wattwise.userapp.util.Constants
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * WattWise Hilt DI module.
 * Provides OkHttpClient, Retrofit, WattWiseApiService and WattWiseAuthApi singletons.
 *
 * The OkHttpClient includes a URL-rewriting interceptor so every request uses
 * the server address the user has saved in Settings.  [ServerConfig.baseUrl] is
 * updated on startup (from DataStore) and whenever the user saves a new address —
 * no Retrofit rebuild needed.
 */
@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideServerConfig(): ServerConfig = ServerConfig()

    @Provides
    @Singleton
    fun provideOkHttpClient(serverConfig: ServerConfig): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.HEADERS
        }

        // Rewrites the host/scheme/port of every outgoing request to match
        // whatever the user has configured as the server URL in Settings.
        val dynamicUrlInterceptor = Interceptor { chain ->
            val original = chain.request()
            val configuredBase = serverConfig.baseUrl.trimEnd('/').toHttpUrl()
            val newUrl = original.url.newBuilder()
                .scheme(configuredBase.scheme)
                .host(configuredBase.host)
                .port(configuredBase.port)
                .build()
            chain.proceed(original.newBuilder().url(newUrl).build())
        }

        return OkHttpClient.Builder()
            .addInterceptor(dynamicUrlInterceptor)
            .addInterceptor(logging)
            .connectTimeout(Constants.DEFAULT_TIMEOUT.toLong(), TimeUnit.SECONDS)
            .readTimeout(Constants.DEFAULT_TIMEOUT.toLong(), TimeUnit.SECONDS)
            .writeTimeout(Constants.DEFAULT_TIMEOUT.toLong(), TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(client: OkHttpClient): Retrofit {
        // Base URL is a placeholder — the dynamic interceptor rewrites the host
        // on every request to the user-configured address.
        return Retrofit.Builder()
            .baseUrl("${Constants.DEFAULT_SERVER_URL}/")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }

    @Provides
    @Singleton
    fun provideWattWiseApiService(retrofit: Retrofit): WattWiseApiService {
        return retrofit.create(WattWiseApiService::class.java)
    }

    @Provides
    @Singleton
    fun provideWattWiseAuthApi(retrofit: Retrofit): WattWiseAuthApi {
        return retrofit.create(WattWiseAuthApi::class.java)
    }
}
