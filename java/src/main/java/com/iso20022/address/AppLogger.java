package com.iso20022.address;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.encoder.PatternLayoutEncoder;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.rolling.FixedWindowRollingPolicy;
import ch.qos.logback.core.rolling.RollingFileAppender;
import ch.qos.logback.core.rolling.SizeBasedTriggeringPolicy;
import ch.qos.logback.core.util.FileSize;
import org.slf4j.LoggerFactory;

import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Singleton application logger (equivalent to Python AppLogger).
 * Uses SLF4J with Logback for rotating file-based logging.
 */
public final class AppLogger {

    private static final String LOGGER_NAME = "structured_address";
    private static volatile AppLogger instance;
    private final Logger logger;
    private boolean configured = false;

    private AppLogger() {
        logger = (Logger) LoggerFactory.getLogger(LOGGER_NAME);
        logger.setLevel(Level.DEBUG);
    }

    public static AppLogger getInstance() {
        if (instance == null) {
            synchronized (AppLogger.class) {
                if (instance == null) {
                    instance = new AppLogger();
                }
            }
        }
        return instance;
    }

    /**
     * Configure file logging to specified directory.
     *
     * @param logDir directory for log files
     * @return true if configuration succeeded
     */
    public boolean configure(Path logDir) {
        try {
            Files.createDirectories(logDir);
            Path logFile = logDir.resolve("application.log");

            LoggerContext context = (LoggerContext) LoggerFactory.getILoggerFactory();

            // Clear existing appenders
            logger.detachAndStopAllAppenders();

            // Pattern encoder
            PatternLayoutEncoder encoder = new PatternLayoutEncoder();
            encoder.setContext(context);
            encoder.setPattern("%d{yyyy-MM-dd HH:mm:ss} - %logger{36} - %level - %msg%n");
            encoder.start();

            // Rolling file appender
            RollingFileAppender<ILoggingEvent> fileAppender = new RollingFileAppender<>();
            fileAppender.setContext(context);
            fileAppender.setFile(logFile.toString());
            fileAppender.setEncoder(encoder);

            // Rolling policy
            FixedWindowRollingPolicy rollingPolicy = new FixedWindowRollingPolicy();
            rollingPolicy.setContext(context);
            rollingPolicy.setParent(fileAppender);
            rollingPolicy.setFileNamePattern(logDir.resolve("application.%i.log").toString());
            rollingPolicy.setMinIndex(1);
            rollingPolicy.setMaxIndex(10);
            rollingPolicy.start();

            // Size-based triggering policy (15MB)
            SizeBasedTriggeringPolicy<ILoggingEvent> triggeringPolicy = new SizeBasedTriggeringPolicy<>();
            triggeringPolicy.setMaxFileSize(FileSize.valueOf("15MB"));
            triggeringPolicy.start();

            fileAppender.setRollingPolicy(rollingPolicy);
            fileAppender.setTriggeringPolicy(triggeringPolicy);
            fileAppender.start();

            logger.addAppender(fileAppender);

            configured = true;
            logger.info("Logging configured to {}", logFile);
            return true;

        } catch (Exception e) {
            logger.error("Failed to configure file logging: {}", e.getMessage());
            return false;
        }
    }

    public boolean isConfigured() {
        return configured;
    }

    public static org.slf4j.Logger getLogger() {
        return getInstance().logger;
    }
}
