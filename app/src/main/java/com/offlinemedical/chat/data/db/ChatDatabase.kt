package com.offlinemedical.chat.data.db

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(entities = [MessageEntity::class, ConversationEntity::class], version = 1, exportSchema = false)
abstract class ChatDatabase : RoomDatabase() {
    abstract fun messageDao(): MessageDao
    abstract fun conversationDao(): ConversationDao
}
