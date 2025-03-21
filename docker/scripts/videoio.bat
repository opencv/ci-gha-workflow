@ECHO OFF


SET VIDEOIO_TMP_FILE="videoio-test"

:LOOP
IF NOT EXIST %CI_SCRIPTS%\%VIDEOIO_TMP_FILE% (
  GOTO CONTINUE
) ELSE (
  ECHO Waiting for a runner
  sleep 30s
  GOTO LOOP
)

:CONTINUE
touch %CI_SCRIPTS%\%VIDEOIO_TMP_FILE%
%cd%\bin\opencv_test_videoio.exe --skip_unstable --gtest_filter=${{ env.GTEST_FILTER_STRING }} --test_threads=%PARALLEL_JOBS%
rm %CI_SCRIPTS%\%VIDEOIO_TMP_FILE%
