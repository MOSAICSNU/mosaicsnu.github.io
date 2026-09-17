# MOSAIC v0.2.0 빠른 안내

Python 3.10 이상을 설치하고 로컬 폴더에서 Windows는 `run_app.bat`,
macOS는 `run_app.command`를 실행합니다. 첫 실행에는 인터넷이 필요합니다.

1. Open ND2로 단일 채널 시계열 영상을 엽니다.
2. Add Background로 세포 없는 곳에 배경 ROI를 놓습니다.
3. Add ROI로 세포/세포 일부를 지정하고 Calculate를 누릅니다.
4. 주황색 Tran. 범위를 안정적인 자극 구간으로 지정합니다.
5. Pacing interval을 확인합니다. 기본값은 2 Hz 자극용 450 ms입니다.
   다른 자극 빈도에서는 자극 간격 × 0.9를 입력합니다(1 Hz는 900 ms).
6. 필요하면 Cal. Photobleaching으로 미리 보고 빨간 점이 기저선에만
   놓였는지 확인한 뒤 Confirm Photobleaching을 누릅니다.
7. Calculate transients 후 개별 이벤트를 확인하고 Use로 포함 여부를 정합니다.
8. Save ROI로 확정합니다. 다른 세포도 반복한 후 Save로 내보냅니다.

마지막 정점 뒤에는 최소 한 자극 간격의 여유가 있어야 합니다.
ROI를 옮기면 Calculate부터 다시 수행합니다. 원본 신호와 검출 수를 비교하세요.

결과는 ND2 옆 `<파일명>_ana` 폴더의 Excel 3개, ROI.jpg,
analysis_info.json에 기록됩니다. Excel 요약은 숫자로 저장됩니다.
Save를 다시 누르면 기존 결과를 덮어쓰므로 독립된 분석은 별도 복사본에서 합니다.

Load Info는 저장 결과를 재계산하지 않고 복원합니다. ND2를 옮겼다면 가까운
경로에서 찾거나 선택창에서 원본을 지정합니다. 새 JSON에는 ROI별 계산 설정과
버전이 들어갑니다. v0.1.0 JSON도 읽지만 당시 저장하지 않은 설정은 알 수 없습니다.
저장 결과를 열어도 입력창 전체가 해당 ROI의 설정으로 자동 변경되지는 않으므로
재분석 전에 JSON의 analysis_settings와 실제 입력값을 확인하십시오.

전체 버튼은 [영문 사용 설명서](USER_GUIDE.md), 계산 정의는
[분석 방법](ANALYSIS_METHODS.md)을 참고하십시오. 별도 홈페이지 그림 설명서는
v0.1.0 기준이므로 버전별 설정과 기대값을 구분해야 합니다.
