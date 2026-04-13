package com.anomalydetector.di

import android.content.Context
import androidx.room.Room
import com.anomalydetector.data.local.AlertDao
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.local.BehaviorEventDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): AppDatabase {
        return Room.databaseBuilder(
            context,
            AppDatabase::class.java,
            "anomaly_detector.db"
        ).fallbackToDestructiveMigration().build()
    }

    @Provides
    fun provideBehaviorEventDao(db: AppDatabase): BehaviorEventDao = db.behaviorEventDao()

    @Provides
    fun provideAlertDao(db: AppDatabase): AlertDao = db.alertDao()
}
